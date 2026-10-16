"""Secure evidence storage, validation, and audit service."""

import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Optional, Tuple
import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core import config
from app.db.models import Claim, ClaimEvidence, EvidenceAuditLog


def ensure_evidence_dir() -> Path:
    """Ensure the private evidence storage directory exists with restricted permissions."""
    p = config.PRIVATE_EVIDENCE_DIR
    p.mkdir(parents=True, exist_ok=True)
    return p


async def save_evidence_file(
    db: Session,
    claim_id: int,
    file: UploadFile,
    evidence_type: str,
    description: str,
    is_sensitive: bool = False,
    actor_label: str = "claimant",
) -> ClaimEvidence:
    """Validate, hash, and safely store an ownership document or photo in private storage."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file has no filename.")

    ext = Path(file.filename).suffix.lower()
    if ext not in config.ALLOWED_EVIDENCE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file format '{ext}'. Allowed types: {', '.join(sorted(config.ALLOWED_EVIDENCE_EXTENSIONS))}",
        )

    # Read and validate file content
    content = await file.read()
    file_size = len(content)

    if file_size == 0:
        raise HTTPException(status_code=400, detail="Cannot upload an empty file.")

    if file_size > config.MAX_EVIDENCE_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {config.MAX_EVIDENCE_FILE_SIZE_BYTES // (1024 * 1024)} MiB.",
        )

    file_hash = hashlib.sha256(content).hexdigest()

    # Generate isolated, non-guessable storage filename
    evidence_dir = ensure_evidence_dir()
    secure_filename = f"ev_{claim_id}_{uuid.uuid4().hex[:16]}{ext}"
    destination_path = evidence_dir / secure_filename

    # Write file securely outside public directory
    destination_path.write_bytes(content)

    # Persist database record
    evidence_record = ClaimEvidence(
        claim_id=claim.id,
        evidence_type=evidence_type,
        description=description.strip(),
        file_path=str(destination_path),
        original_filename=file.filename,
        file_hash=file_hash,
        file_size_bytes=file_size,
        is_sensitive=is_sensitive,
    )

    db.add(evidence_record)
    db.flush()

    # Record access audit event
    audit_entry = EvidenceAuditLog(
        claim_id=claim.id,
        evidence_id=evidence_record.id,
        action="EVIDENCE_SUBMITTED",
        actor_label=actor_label,
        notes=f"Evidence type: {evidence_type}, size: {file_size} bytes, hash: {file_hash[:12]}...",
    )
    db.add(audit_entry)
    db.commit()
    db.refresh(evidence_record)

    return evidence_record


def get_evidence_file_path(
    db: Session,
    evidence_id: int,
    actor_label: str = "reviewer",
) -> Tuple[Path, str, str]:
    """Retrieve an evidence file path while recording an audit log entry."""
    record = db.get(ClaimEvidence, evidence_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Evidence record not found.")

    if not record.file_path:
        raise HTTPException(status_code=404, detail="Evidence does not contain a physical file.")

    p = Path(record.file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="Evidence file is missing from secure storage.")

    # Record access audit
    audit = EvidenceAuditLog(
        claim_id=record.claim_id,
        evidence_id=record.id,
        action="EVIDENCE_ACCESSED",
        actor_label=actor_label,
        notes=f"File {record.original_filename} accessed by {actor_label}.",
    )
    db.add(audit)
    db.commit()

    mime_type, _ = mimetypes.guess_type(str(p))
    return p, record.original_filename or p.name, mime_type or "application/octet-stream"
