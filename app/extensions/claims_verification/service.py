"""Business logic for verified claim submission, contact status, and supplemental evidence."""

from typing import Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimVerificationDetail,
    EvidenceAuditLog,
    ItemReport,
)
from app.extensions.claims_verification.schemas import (
    VerificationStatus,
    VerifiedClaimCreate,
    VerifiedClaimResponse,
)


def submit_verified_claim(
    db: Session,
    found_report_id: int,
    payload: VerifiedClaimCreate,
) -> Tuple[Claim, ClaimVerificationDetail]:
    """Validate reports and create a claim with comprehensive verification metadata."""
    if not payload.privacy_consent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent to the data handling and verification policy is mandatory to submit a claim.",
        )

    # 1. Validate Found Report
    found_report = db.get(ItemReport, found_report_id)
    if found_report is None:
        raise HTTPException(status_code=404, detail="Found report not found.")
    if found_report.report_type != "found":
        raise HTTPException(status_code=400, detail="Claims must reference an active found-item report.")
    if found_report.status != "active":
        raise HTTPException(status_code=400, detail="This found-item report is no longer active.")

    # 2. Validate Lost Report
    lost_report = db.get(ItemReport, payload.lost_report_id)
    if lost_report is None:
        raise HTTPException(status_code=404, detail="Lost report not found.")
    if lost_report.report_type != "lost":
        raise HTTPException(status_code=400, detail="The claimant's referenced report must be a lost-item report.")
    if lost_report.status != "active":
        raise HTTPException(status_code=400, detail="The referenced lost-item report is not active.")

    # 3. Anti-abuse: A report cannot claim itself
    if found_report.id == lost_report.id:
        raise HTTPException(status_code=400, detail="A report cannot be claimed against itself.")

    # 4. Check for existing active or approved claims by this claimant
    existing_claim = db.scalars(
        select(Claim).where(
            Claim.found_report_id == found_report.id,
            Claim.lost_report_id == lost_report.id,
            Claim.status.in_(["pending", "approved"]),
        )
    ).first()
    if existing_claim is not None:
        raise HTTPException(
            status_code=409,
            detail=f"An active claim (#{existing_claim.id}) already exists between these reports.",
        )

    try:
        # Base claim record compatible with core schema
        claim = Claim(
            lost_report_id=lost_report.id,
            found_report_id=found_report.id,
            claimant_name=payload.claimant_name.strip(),
            contact_email=str(payload.contact_email).strip().lower(),
            claim_message=payload.claim_message.strip(),
            status="pending",
        )
        db.add(claim)
        db.flush()

        # Detailed verification record
        detail = ClaimVerificationDetail(
            claim_id=claim.id,
            verification_status=VerificationStatus.SUBMITTED.value,
            contact_phone=payload.contact_phone.strip() if payload.contact_phone else None,
            phone_verified=False,
            email_verified=False,
            verification_method="unverified",
            serial_number=payload.serial_number.strip() if payload.serial_number else None,
            identifying_features=payload.identifying_features.strip() if payload.identifying_features else None,
            distinctive_marks=payload.distinctive_marks.strip() if payload.distinctive_marks else None,
            privacy_consent=True,
        )
        db.add(detail)

        # Audit entry
        audit = EvidenceAuditLog(
            claim_id=claim.id,
            action="CLAIM_SUBMITTED",
            actor_label="claimant",
            notes="Initial claim submission with verification details.",
        )
        db.add(audit)

        db.commit()
        db.refresh(claim)
        db.refresh(detail)
        return claim, detail

    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to submit claim: {str(exc)}")


def submit_additional_information(
    db: Session,
    claim_id: int,
    additional_info: str,
) -> ClaimVerificationDetail:
    """Allow claimant to provide answers or supplementary evidence requested by reviewer."""
    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim_id)
    ).first()

    if detail is None:
        raise HTTPException(status_code=404, detail="Claim verification record not found.")

    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    if detail.verification_status not in [
        VerificationStatus.ADDITIONAL_INFORMATION_REQUIRED.value,
        VerificationStatus.SUBMITTED.value,
        VerificationStatus.UNDER_REVIEW.value,
    ]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot submit additional info when claim is in '{detail.verification_status}' status.",
        )

    # Append new response
    clean_info = additional_info.strip()
    if detail.additional_info_provided:
        detail.additional_info_provided += f"\n---\n{clean_info}"
    else:
        detail.additional_info_provided = clean_info

    # Move status back to under_review for reviewer evaluation
    detail.verification_status = VerificationStatus.UNDER_REVIEW.value

    audit = EvidenceAuditLog(
        claim_id=claim.id,
        action="ADDITIONAL_INFO_SUBMITTED",
        actor_label="claimant",
        notes="Claimant responded to reviewer request for information.",
    )
    db.add(audit)
    db.commit()
    db.refresh(detail)
    return detail


def get_verified_claim_response(db: Session, claim_id: int) -> VerifiedClaimResponse:
    """Build a public-safe status response for a claim."""
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found.")

    detail = db.scalars(
        select(ClaimVerificationDetail).where(ClaimVerificationDetail.claim_id == claim.id)
    ).first()

    v_status = detail.verification_status if detail else claim.status
    phone_v = detail.phone_verified if detail else False
    email_v = detail.email_verified if detail else False
    method = detail.verification_method if detail else "unverified"
    phone = detail.contact_phone if detail else None
    req_info = detail.additional_info_requested if detail else None

    # Count attached evidence files
    ev_count = len(db.scalars(
        select(ClaimEvidence).where(ClaimEvidence.claim_id == claim.id)
    ).all())

    public_status_messages = {
        VerificationStatus.SUBMITTED.value: "Your claim has been submitted and is queued for reviewer evaluation.",
        VerificationStatus.CONTACT_VERIFICATION_PENDING.value: "Pending manual or institutional contact verification.",
        VerificationStatus.UNDER_REVIEW.value: "An authorized reviewer is currently examining your claim evidence.",
        VerificationStatus.ADDITIONAL_INFORMATION_REQUIRED.value: f"Action required: The reviewer requested further details: '{req_info}'. Please submit additional information below.",
        VerificationStatus.APPROVED.value: "Your claim has been approved! Next step: Handover coordination.",
        VerificationStatus.REJECTED.value: "Your claim was not approved based on the submitted evidence.",
        VerificationStatus.HANDOVER_PENDING.value: "Your claim is approved. Handover with the finder or campus desk is in progress.",
        VerificationStatus.COMPLETED.value: "Item recovery completed and verified.",
        VerificationStatus.SUSPECTED_FRAUD_REVIEW.value: "This claim is held for administrative review.",
    }

    return VerifiedClaimResponse(
        id=claim.id,
        lost_report_id=claim.lost_report_id,
        found_report_id=claim.found_report_id,
        claimant_name=claim.claimant_name,
        contact_email=claim.contact_email,
        contact_phone=phone,
        phone_verified=phone_v,
        email_verified=email_v,
        verification_method=method,
        status=claim.status,
        verification_status=v_status,
        created_at=claim.created_at,
        evidence_count=ev_count,
        additional_info_requested=req_info,
        public_status_message=public_status_messages.get(v_status, "Claim status: " + v_status),
    )
