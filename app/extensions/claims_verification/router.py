"""FastAPI router for verified claims submission and evidence upload."""

from typing import Annotated
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.extensions.claims_verification.evidence_service import save_evidence_file
from app.extensions.claims_verification.schemas import (
    AdditionalInfoSubmission,
    EvidenceItemResponse,
    VerifiedClaimCreate,
    VerifiedClaimResponse,
)
from app.extensions.claims_verification.service import (
    get_verified_claim_response,
    submit_additional_information,
    submit_verified_claim,
)

router = APIRouter(
    prefix="/api/verification/claims",
    tags=["Claim Verification"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/{found_report_id}",
    response_model=VerifiedClaimResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a verified claim with ownership evidence",
    description="Submit a claim with ownership details, identifying private marks, and privacy consent.",
)
def create_verified_claim_endpoint(
    found_report_id: int,
    payload: VerifiedClaimCreate,
    db: DatabaseSession,
) -> VerifiedClaimResponse:
    """Submit a verified claim against an active found item report."""
    claim, detail = submit_verified_claim(db=db, found_report_id=found_report_id, payload=payload)
    return get_verified_claim_response(db=db, claim_id=claim.id)


@router.post(
    "/{claim_id}/evidence",
    response_model=EvidenceItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload ownership evidence to private storage",
    description="Upload receipts, original photos, or serial documents. Stored securely outside public static directories.",
)
async def upload_claim_evidence_endpoint(
    claim_id: int,
    db: DatabaseSession,
    file: UploadFile = File(..., description="Evidence file (PDF, PNG, JPG, WebP up to 5MB)"),
    evidence_type: str = Form("purchase_receipt", description="Type of evidence"),
    description: str = Form(..., min_length=2, max_length=500, description="Description of the uploaded evidence"),
    is_sensitive: bool = Form(False, description="Flag whether document contains sensitive personal details"),
) -> EvidenceItemResponse:
    """Upload and securely store an evidence file for an existing claim."""
    record = await save_evidence_file(
        db=db,
        claim_id=claim_id,
        file=file,
        evidence_type=evidence_type,
        description=description,
        is_sensitive=is_sensitive,
        actor_label="claimant",
    )
    return EvidenceItemResponse(
        id=record.id,
        claim_id=record.claim_id,
        evidence_type=record.evidence_type,
        description=record.description,
        original_filename=record.original_filename,
        file_size_bytes=record.file_size_bytes,
        is_sensitive=record.is_sensitive,
        created_at=record.created_at,
    )


@router.get(
    "/{claim_id}/status",
    response_model=VerifiedClaimResponse,
    summary="Check claim verification status",
    description="Returns public-safe verification status without exposing reviewer notes.",
)
def get_claim_status_endpoint(
    claim_id: int,
    db: DatabaseSession,
) -> VerifiedClaimResponse:
    """Retrieve public claim status and any pending additional information requests."""
    return get_verified_claim_response(db=db, claim_id=claim_id)


@router.post(
    "/{claim_id}/additional-info",
    response_model=VerifiedClaimResponse,
    summary="Submit additional information requested by reviewer",
    description="Claimant response to reviewer inquiries, moving the claim back to under_review.",
)
def submit_additional_info_endpoint(
    claim_id: int,
    payload: AdditionalInfoSubmission,
    db: DatabaseSession,
) -> VerifiedClaimResponse:
    """Submit responses or clarifying details to an active reviewer inquiry."""
    submit_additional_information(
        db=db,
        claim_id=claim_id,
        additional_info=payload.additional_info,
    )
    return get_verified_claim_response(db=db, claim_id=claim_id)
