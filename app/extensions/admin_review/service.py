"""Reviewer dashboard and administrative claim verification service."""

import json
from typing import Any, Dict, List, Optional
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimHandoverRecord,
    ClaimReviewRecord,
    ClaimVerificationDetail,
    EvidenceAuditLog,
    ItemReport,
    PoliceComplaintDraft,
)
from app.extensions.claims_verification.schemas import VerificationStatus


def list_claims_for_review(
    db: Session,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List claims with associated report names and verification statuses."""
    stmt = select(Claim, ClaimVerificationDetail).outerjoin(
        ClaimVerificationDetail, Claim.id == ClaimVerificationDetail.claim_id
    ).order_by(Claim.created_at.desc()).limit(limit)

    results = db.execute(stmt).all()
    output: List[Dict[str, Any]] = []

    for claim, detail in results:
        v_status = detail.verification_status if detail else claim.status
        if status_filter and status_filter.lower() != "all" and v_status != status_filter:
            continue

        found_item = db.get(ItemReport, claim.found_report_id)
        lost_item = db.get(ItemReport, claim.lost_report_id)

        ev_count = len(
            db.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)).all()
        )

        output.append({
            "claim_id": claim.id,
            "lost_report_id": claim.lost_report_id,
            "found_report_id": claim.found_report_id,
            "item_name": found_item.item_name if found_item else "Unknown",
            "category": found_item.category if found_item else "Other",
            "claimant_name": claim.claimant_name,
            "contact_email": claim.contact_email,
            "contact_phone": detail.contact_phone if detail else None,
            "phone_verified": detail.phone_verified if detail else False,
            "email_verified": detail.email_verified if detail else False,
            "verification_method": detail.verification_method if detail else "unverified",
            "claim_status": claim.status,
            "verification_status": v_status,
            "has_serial": bool(detail.serial_number) if detail else False,
            "has_identifying_features": bool(detail.identifying_features) if detail else False,
            "evidence_count": ev_count,
            "created_at": claim.created_at.isoformat(),
        })

    return output


def get_claim_review_detail(db: Session, claim_id: int) -> Dict[str, Any]:
    """Retrieve full verification dossier for an authorized reviewer."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    found_report = db.get(ItemReport, claim.found_report_id)
    lost_report = db.get(ItemReport, claim.lost_report_id)
    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim.id)
    ).first()

    evidence_records = db.scalars(
        select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id).order_by(ClaimEvidence.created_at)
    ).all()

    review_records = db.scalars(
        select(ClaimReviewRecord).where(ClaimReviewRecord.claim_id == claim.id).order_by(ClaimReviewRecord.reviewed_at)
    ).all()

    handover_record = db.scalars(
        select(ClaimHandoverRecord).where(ClaimHandoverRecord.claim_id == claim.id)
    ).first()

    audit_logs = db.scalars(
        select(EvidenceAuditLog).where(EvidenceAuditLog.claim_id == claim.id).order_by(EvidenceAuditLog.timestamp.desc())
    ).all()

    police_draft = db.scalars(
        select(PoliceComplaintDraft).where(PoliceComplaintDraft.claim_id == claim.id).order_by(PoliceComplaintDraft.created_at.desc())
    ).first()

    return {
        "claim": {
            "id": claim.id,
            "lost_report_id": claim.lost_report_id,
            "found_report_id": claim.found_report_id,
            "claimant_name": claim.claimant_name,
            "contact_email": claim.contact_email,
            "claim_message": claim.claim_message,
            "status": claim.status,
            "created_at": claim.created_at.isoformat(),
        },
        "found_report": {
            "id": found_report.id,
            "item_name": found_report.item_name,
            "category": found_report.category,
            "color": found_report.color,
            "brand": found_report.brand,
            "model": found_report.model,
            "location_text": found_report.location_text,
            "event_date": str(found_report.event_date),
            "status": found_report.status,
        } if found_report else None,
        "lost_report": {
            "id": lost_report.id,
            "item_name": lost_report.item_name,
            "category": lost_report.category,
            "color": lost_report.color,
            "brand": lost_report.brand,
            "model": lost_report.model,
            "location_text": lost_report.location_text,
            "event_date": str(lost_report.event_date),
            "status": lost_report.status,
        } if lost_report else None,
        "verification_detail": {
            "verification_status": detail.verification_status if detail else claim.status,
            "contact_phone": detail.contact_phone if detail else None,
            "phone_verified": detail.phone_verified if detail else False,
            "email_verified": detail.email_verified if detail else False,
            "verification_method": detail.verification_method if detail else "unverified",
            "serial_number": detail.serial_number if detail else None,
            "identifying_features": detail.identifying_features if detail else None,
            "distinctive_marks": detail.distinctive_marks if detail else None,
            "additional_info_requested": detail.additional_info_requested if detail else None,
            "additional_info_provided": detail.additional_info_provided if detail else None,
            "fraud_flag_reason": detail.fraud_flag_reason if detail else None,
        } if detail else None,
        "evidence_files": [
            {
                "id": ev.id,
                "evidence_type": ev.evidence_type,
                "description": ev.description,
                "original_filename": ev.original_filename,
                "file_size_bytes": ev.file_size_bytes,
                "file_hash": ev.file_hash,
                "is_sensitive": ev.is_sensitive,
                "created_at": ev.created_at.isoformat(),
            }
            for ev in evidence_records
        ],
        "review_history": [
            {
                "decision": r.decision,
                "review_note": r.review_note,
                "reviewer_label": r.reviewer_label,
                "reviewed_at": r.reviewed_at.isoformat(),
            }
            for r in review_records
        ],
        "handover": {
            "handover_note": handover_record.handover_note,
            "reviewer_label": handover_record.reviewer_label,
            "handed_over_at": handover_record.handed_over_at.isoformat(),
        } if handover_record else None,
        "police_complaint_draft": {
            "draft_reference": police_draft.draft_reference,
            "status": police_draft.status,
            "police_station_target": police_draft.police_station_target,
            "created_at": police_draft.created_at.isoformat(),
        } if police_draft else None,
        "audit_logs": [
            {
                "action": a.action,
                "actor_label": a.actor_label,
                "notes": a.notes,
                "timestamp": a.timestamp.isoformat(),
            }
            for a in audit_logs
        ],
    }


def request_additional_information(
    db: Session,
    claim_id: int,
    request_note: str,
    reviewer_label: str,
) -> ClaimVerificationDetail:
    """Reviewer requests specific supplemental evidence or answers."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim.id)
    ).first()

    if detail is None:
        # Create detail record if claim predated verification extension
        detail = ClaimVerificationDetail(
            claim_id=claim.id,
            verification_status=VerificationStatus.SUBMITTED.value,
        )
        db.add(detail)

    detail.additional_info_requested = request_note.strip()
    detail.verification_status = VerificationStatus.ADDITIONAL_INFORMATION_REQUIRED.value

    audit = EvidenceAuditLog(
        claim_id=claim.id,
        action="ADDITIONAL_INFO_REQUESTED",
        actor_label=reviewer_label,
        notes=f"Reviewer inquiry: {request_note.strip()}",
    )
    db.add(audit)
    db.commit()
    db.refresh(detail)
    return detail


def record_review_decision(
    db: Session,
    claim_id: int,
    decision: str,
    review_note: str,
    reviewer_label: str,
) -> Claim:
    """Record an approval or rejection with audit trail and competing claim closure."""
    clean_dec = decision.strip().lower()
    if clean_dec not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Decision must be 'approved' or 'rejected'.")

    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    if claim.status not in {"pending", "submitted", "under_review"}:
        raise HTTPException(status_code=400, detail=f"Claim is in '{claim.status}' status and cannot be reviewed.")

    found_report = db.get(ItemReport, claim.found_report_id)
    if found_report is None or found_report.status != "active":
        raise HTTPException(status_code=400, detail="Found report is not active.")

    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim.id)
    ).first()

    if clean_dec == "approved":
        # Check competing approvals
        existing_approval = db.scalars(
            select(Claim).where(
                Claim.found_report_id == claim.found_report_id,
                Claim.status == "approved",
                Claim.id != claim.id,
            )
        ).first()
        if existing_approval is not None:
            raise HTTPException(status_code=400, detail="Another claim for this found item is already approved.")

        claim.status = "approved"
        if detail:
            detail.verification_status = VerificationStatus.APPROVED.value
    else:
        claim.status = "rejected"
        if detail:
            detail.verification_status = VerificationStatus.REJECTED.value

    # Add core review record
    db.add(
        ClaimReviewRecord(
            claim_id=claim.id,
            decision=clean_dec,
            review_note=review_note.strip(),
            reviewer_label=reviewer_label,
        )
    )

    # Reject competing claims on approval
    if clean_dec == "approved":
        competing_claims = db.scalars(
            select(Claim).where(
                Claim.found_report_id == claim.found_report_id,
                Claim.status == "pending",
                Claim.id != claim.id,
            )
        ).all()
        for cc in competing_claims:
            cc.status = "rejected"
            cc_detail = db.scalars(
                select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == cc.id)
            ).first()
            if cc_detail:
                cc_detail.verification_status = VerificationStatus.REJECTED.value
            db.add(
                ClaimReviewRecord(
                    claim_id=cc.id,
                    decision="rejected",
                    review_note=f"Rejected: Competing claim #{claim.id} was verified and approved.",
                    reviewer_label=reviewer_label,
                )
            )

    # Audit entry
    db.add(
        EvidenceAuditLog(
            claim_id=claim.id,
            action=f"CLAIM_{clean_dec.upper()}",
            actor_label=reviewer_label,
            notes=review_note.strip(),
        )
    )

    db.commit()
    db.refresh(claim)
    return claim


def flag_suspected_fraud(
    db: Session,
    claim_id: int,
    fraud_reason: str,
    reviewer_label: str,
) -> ClaimVerificationDetail:
    """Escalate a suspicious claim for fraud review without public disclosure."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim.id)
    ).first()

    if detail is None:
        detail = ClaimVerificationDetail(claim_id=claim.id)
        db.add(detail)

    detail.verification_status = VerificationStatus.SUSPECTED_FRAUD_REVIEW.value
    detail.fraud_flag_reason = fraud_reason.strip()

    audit = EvidenceAuditLog(
        claim_id=claim.id,
        action="FLAGGED_FRAUD_REVIEW",
        actor_label=reviewer_label,
        notes=f"Escalated for fraud review: {fraud_reason.strip()}",
    )
    db.add(audit)
    db.commit()
    db.refresh(detail)
    return detail


def generate_police_complaint_draft(
    db: Session,
    claim_id: int,
    reviewer_label: str,
    target_station: Optional[str] = None,
) -> PoliceComplaintDraft:
    """Generate a formal, human-reviewable police complaint draft packet."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    found_report = db.get(ItemReport, claim.found_report_id)
    lost_report = db.get(ItemReport, claim.lost_report_id)
    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim.id)
    ).first()

    evidence_records = db.scalars(
        select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)
    ).all()

    audit_logs = db.scalars(
        select(EvidenceAuditLog).where(EvidenceAuditLog.claim_id == claim.id).order_by(EvidenceAuditLog.timestamp)
    ).all()

    fraud_reason = detail.fraud_flag_reason if (detail and detail.fraud_flag_reason) else "Documented suspicion of deliberate misrepresentation during property claim."

    # Build factual timeline
    timeline_entries = [
        f"[{found_report.created_at.strftime('%Y-%m-%d %H:%M')}] Found report #{found_report.id} published: '{found_report.item_name}' at {found_report.location_text}",
        f"[{lost_report.created_at.strftime('%Y-%m-%d %H:%M')}] Lost report #{lost_report.id} created: '{lost_report.item_name}'",
        f"[{claim.created_at.strftime('%Y-%m-%d %H:%M')}] Claim #{claim.id} submitted by '{claim.claimant_name}' ({claim.contact_email})",
    ]
    for log in audit_logs:
        timeline_entries.append(f"[{log.timestamp.strftime('%Y-%m-%d %H:%M')}] Action: {log.action} by {log.actor_label}: {log.notes or 'No notes'}")

    timeline_text = "\n".join(timeline_entries)

    # Shareable contact info
    contacts = [
        f"Claimant Name: {claim.claimant_name}",
        f"Contact Email: {claim.contact_email}",
        f"Contact Phone: {detail.contact_phone if detail and detail.contact_phone else 'Not provided'}",
        f"Phone Verified: {'Yes' if detail and detail.phone_verified else 'No'}",
        f"Email Verified: {'Yes' if detail and detail.email_verified else 'No'}",
    ]
    contact_text = "\n".join(contacts)

    # Evidence references
    evidence_desc = [
        f"Evidence #{ev.id}: Type={ev.evidence_type}, File={ev.original_filename or 'None'}, Hash={ev.file_hash or 'N/A'}, Notes={ev.description}"
        for ev in evidence_records
    ] or ["No evidence files attached."]
    evidence_text = "\n".join(evidence_desc)

    incident_summary = (
        f"Suspicious claim #{claim.id} filed for recovered property '{found_report.item_name}' (Report #{found_report.id}). "
        f"Claimant '{claim.claimant_name}' asserted ownership, but evidence or verification revealed material inconsistencies requiring formal inquiry."
    )

    observations = (
        f"1. Item reported found: {found_report.item_name} on {found_report.event_date}.\n"
        f"2. Claimant statements: \"{claim.claim_message}\"\n"
        f"3. Attached Evidence Items: {len(evidence_records)} items on record.\n"
        f"4. Fraud Review Reason: {fraud_reason}\n"
        f"5. IMPORTANT: This package is a factual administrative draft for authorized human review and lawful police submission. It does not constitute a judicial finding."
    )

    draft = PoliceComplaintDraft(
        draft_reference=f"PCD-{claim.id}-{uuid.uuid4().hex[:8].upper()}",
        claim_id=claim.id,
        found_report_id=found_report.id,
        lost_report_id=lost_report.id,
        incident_summary=incident_summary,
        fraud_indicators=fraud_reason,
        event_timeline=timeline_text,
        shareable_contact_info=contact_text,
        reviewer_observations=observations,
        prepared_by=reviewer_label,
        status="draft_pending_human_submission",
        police_station_target=target_station or "Local Jurisdiction Police Station",
    )
    db.add(draft)

    audit = EvidenceAuditLog(
        claim_id=claim.id,
        action="POLICE_COMPLAINT_DRAFT_CREATED",
        actor_label=reviewer_label,
        notes=f"Draft reference {draft.draft_reference} prepared for manual police submission.",
    )
    db.add(audit)
    db.commit()
    db.refresh(draft)
    return draft
