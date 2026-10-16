
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Claim,
    ClaimHandoverRecord,
    ClaimReviewRecord,
    ItemReport,
)





def review_claim(
    db: Session,
    claim_id: int,
    decision: str,
    review_note: str,
    reviewer_label: str,
) -> Claim:
    """Review a claim and record the decision."""

    if decision not in {"approved", "rejected"}:
        raise ValueError("Decision must be approved or rejected.")

    claim = db.get(Claim, claim_id)

    if claim is None:
        raise ValueError("Claim not found.")

    if claim.status != "pending":
        raise ValueError("Only pending claims can be reviewed.")

    found_report = db.get(ItemReport, claim.found_report_id)

    if found_report is None:
        raise ValueError("Found report not found.")

    if found_report.status != "active":
        raise ValueError("Found report is no longer active.")

    # Check whether another claim has already been approved.
    if decision == "approved":
        existing_approval = db.scalars(
            select(Claim).where(
                Claim.found_report_id == claim.found_report_id,
                Claim.status == "approved",
                Claim.id != claim.id,
            )
        ).first()

        if existing_approval is not None:
            raise ValueError(
                "Another claim for this item is already approved."
            )

    try:
        # Save the reviewer's decision for the selected claim.
        claim.status = decision

        db.add(
            ClaimReviewRecord(
                claim_id=claim.id,
                decision=decision,
                review_note=review_note.strip(),
                reviewer_label=reviewer_label,
            )
        )

        # If approved, close the other pending claims for this item.
        if decision == "approved":
            competing_claims = db.scalars(
                select(Claim).where(
                    Claim.found_report_id == claim.found_report_id,
                    Claim.status == "pending",
                    Claim.id != claim.id,
                )
            ).all()

            for competing_claim in competing_claims:
                competing_claim.status = "rejected"

                db.add(
                    ClaimReviewRecord(
                        claim_id=competing_claim.id,
                        decision="rejected",
                        review_note=(
                            "Not selected because another claim for "
                            "this item was approved. Original claim "
                            "review note: "
                            + review_note.strip()
                        ),
                        reviewer_label=reviewer_label,
                    )
                )

        # Save all status changes and review records together.
        db.commit()
        db.refresh(claim)

    except Exception:
        db.rollback()
        raise

    return claim





def complete_handover(
    db: Session,
    claim_id: int,
    handover_note: str,
    reviewer_label: str,
) -> Claim:
    """
    Record the physical return of an item after claim approval.
    """

    # 1. Find the claim.
    claim = db.get(Claim, claim_id)

    if claim is None:
        raise ValueError("Claim not found.")

    # 2. Handover is permitted only for approved claims.
    if claim.status != "approved":
        raise ValueError("Only approved claims can be handed over.")

    # 3. Find the associated found-item report.
    found_report = db.get(ItemReport, claim.found_report_id)

    if found_report is None:
        raise ValueError("Found report not found.")

    if found_report.status != "active":
        raise ValueError("Found report is no longer active.")

    # 4. Save the handover record and update both statuses.
    try:
        handover_record = ClaimHandoverRecord(
            claim_id=claim.id,
            handover_note=handover_note.strip(),
            reviewer_label=reviewer_label,
        )

        db.add(handover_record)

        # The claim is now completed.
        claim.status = "completed"

        # The found item is no longer available.
        found_report.status = "returned"

        db.commit()
        db.refresh(claim)

    except Exception:
        db.rollback()
        raise

    return claim
