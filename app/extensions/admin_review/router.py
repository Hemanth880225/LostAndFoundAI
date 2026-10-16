"""Reviewer administrative API router for claim verification, fraud review, and evidence inspection."""

from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.reviewer_auth import require_reviewer
from app.db.database import get_db
from app.extensions.admin_review.service import (
    flag_suspected_fraud,
    generate_police_complaint_draft,
    get_claim_review_detail,
    list_claims_for_review,
    record_review_decision,
    request_additional_information,
)
from app.extensions.claims_verification.evidence_service import get_evidence_file_path

router = APIRouter(
    prefix="/api/admin/claims",
    tags=["Reviewer Claims Management"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]
ReviewerAuth = Annotated[str, Depends(require_reviewer)]


class RequestInfoPayload(BaseModel):
    request_note: str = Field(min_length=5, max_length=1000, description="Specific questions or evidence requested from claimant")


class ReviewDecisionPayload(BaseModel):
    decision: str = Field(..., description="'approved' or 'rejected'")
    review_note: str = Field(min_length=5, max_length=1000, description="Factual basis for review decision")


class FlagFraudPayload(BaseModel):
    fraud_reason: str = Field(min_length=10, max_length=2000, description="Documented indicators of suspected deliberate deception")


class PoliceDraftPayload(BaseModel):
    target_station: Optional[str] = Field(default=None, max_length=200, description="Jurisdictional police station or cyber cell")


@router.get(
    "",
    summary="List claims for administrative review",
    description="Reviewer-only endpoint to list pending, active, and completed claims with verification details.",
)
def list_claims_endpoint(
    db: DatabaseSession,
    reviewer: ReviewerAuth,
    status_filter: Optional[str] = Query("all", description="Filter by status (all, submitted, under_review, additional_information_required, approved, rejected, completed, suspected_fraud_review)"),
    limit: int = Query(50, ge=1, le=100),
) -> List[Dict[str, Any]]:
    return list_claims_for_review(db=db, status_filter=status_filter, limit=limit)


@router.get(
    "/{claim_id}",
    summary="Get comprehensive claim verification dossier",
    description="Reviewer-only inspection of claim, matched reports, evidence metadata, and audit trail.",
)
def get_claim_detail_endpoint(
    claim_id: int,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> Dict[str, Any]:
    return get_claim_review_detail(db=db, claim_id=claim_id)


@router.get(
    "/{claim_id}/evidence/{evidence_id}/file",
    summary="Download or view private evidence file",
    description="Secure reviewer-only access to private receipts, photos, and documents. Access is audited.",
)
def download_evidence_file_endpoint(
    claim_id: int,
    evidence_id: int,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
):
    path, filename, mime_type = get_evidence_file_path(db=db, evidence_id=evidence_id, actor_label=reviewer)
    return FileResponse(
        path=path,
        filename=filename,
        media_type=mime_type,
        headers={"Cache-Control": "no-store, private"},
    )


@router.post(
    "/{claim_id}/request-info",
    summary="Request additional information from claimant",
    description="Sets status to additional_information_required and records inquiry note.",
)
def request_info_endpoint(
    claim_id: int,
    payload: RequestInfoPayload,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> Dict[str, Any]:
    detail = request_additional_information(
        db=db,
        claim_id=claim_id,
        request_note=payload.request_note,
        reviewer_label=reviewer,
    )
    return {
        "claim_id": claim_id,
        "verification_status": detail.verification_status,
        "additional_info_requested": detail.additional_info_requested,
    }


@router.post(
    "/{claim_id}/decide",
    summary="Record formal approval or rejection decision",
    description="Approve or reject claim with required audit reasoning.",
)
def decide_claim_endpoint(
    claim_id: int,
    payload: ReviewDecisionPayload,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> Dict[str, Any]:
    claim = record_review_decision(
        db=db,
        claim_id=claim_id,
        decision=payload.decision,
        review_note=payload.review_note,
        reviewer_label=reviewer,
    )
    return {
        "claim_id": claim.id,
        "status": claim.status,
        "decision": payload.decision,
    }


@router.post(
    "/{claim_id}/flag-fraud",
    summary="Escalate claim for suspected fraud review",
    description="Moves claim to suspected_fraud_review with documented indicators. Not exposed to public.",
)
def flag_fraud_endpoint(
    claim_id: int,
    payload: FlagFraudPayload,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> Dict[str, Any]:
    detail = flag_suspected_fraud(
        db=db,
        claim_id=claim_id,
        fraud_reason=payload.fraud_reason,
        reviewer_label=reviewer,
    )
    return {
        "claim_id": claim_id,
        "verification_status": detail.verification_status,
        "fraud_flag_reason": detail.fraud_flag_reason,
    }


@router.post(
    "/{claim_id}/police-draft",
    summary="Prepare police complaint draft packet",
    description="Generates an auditable draft packet with timeline, evidence, and observations for human-approved police escalation.",
)
def prepare_police_draft_endpoint(
    claim_id: int,
    payload: PoliceDraftPayload,
    db: DatabaseSession,
    reviewer: ReviewerAuth,
) -> Dict[str, Any]:
    draft = generate_police_complaint_draft(
        db=db,
        claim_id=claim_id,
        reviewer_label=reviewer,
        target_station=payload.target_station,
    )
    return {
        "draft_reference": draft.draft_reference,
        "status": draft.status,
        "incident_summary": draft.incident_summary,
        "fraud_indicators": draft.fraud_indicators,
        "event_timeline": draft.event_timeline,
        "shareable_contact_info": draft.shareable_contact_info,
        "reviewer_observations": draft.reviewer_observations,
        "police_station_target": draft.police_station_target,
        "created_at": draft.created_at.isoformat(),
    }
