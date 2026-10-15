
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Claim, ItemReport
from app.schemas.claims import ClaimCreate, ClaimResponse


router = APIRouter(
    prefix="/api/reports",
    tags=["Claims"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "/{found_report_id}/claims",
    response_model=ClaimResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_claim(
    found_report_id: int,
    payload: ClaimCreate,
    db: DatabaseSession,
):
    """Submit a claim against a found-item report."""

    found_report = db.get(ItemReport, found_report_id)

    if found_report is None:
        raise HTTPException(
            status_code=404,
            detail="Found report not found.",
        )

    if found_report.report_type != "found":
        raise HTTPException(
            status_code=400,
            detail="Claims must reference a found-item report.",
        )

    if found_report.status != "active":
        raise HTTPException(
            status_code=400,
            detail="This found-item report is not active.",
        )

    lost_report = db.get(
        ItemReport,
        payload.lost_report_id,
    )

    if lost_report is None:
        raise HTTPException(
            status_code=404,
            detail="Lost report not found.",
        )

    if lost_report.report_type != "lost":
        raise HTTPException(
            status_code=400,
            detail="The claimant's report must be a lost-item report.",
        )

    if lost_report.status != "active":
        raise HTTPException(
            status_code=400,
            detail="The lost-item report is not active.",
        )

    claim = Claim(
        lost_report_id=lost_report.id,
        found_report_id=found_report.id,
        claimant_name=payload.claimant_name.strip(),
        contact_email=str(payload.contact_email),
        claim_message=payload.claim_message.strip(),
        status="pending",
    )

    try:
        db.add(claim)
        db.commit()
        db.refresh(claim)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not submit the claim.",
        )

    return claim

