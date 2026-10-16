from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import (
    Claim,
    ClaimHandoverRecord,
    ClaimReviewRecord,
    ItemReport,
)
from app.services.claim_service import review_claim, complete_handover


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    session = TestingSessionLocal()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def make_report(db, report_type, item_name, status="active"):
    report = ItemReport(
        report_type=report_type,
        item_name=item_name,
        category="electronics",
        color="black",
        description=f"Black {item_name}",
        event_date=date(2026, 10, 10),
        location_text="College library",
        latitude=18.5204,
        longitude=73.8567,
        status=status,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def make_claim(db, found_report, lost_report=None, status="pending"):
    if lost_report is None:
        lost_report = make_report(db, "lost", "Phone")

    claim = Claim(
        lost_report_id=lost_report.id,
        found_report_id=found_report.id,
        claimant_name="Test Claimant",
        contact_email="claimant@example.com",
        claim_message="I can identify the item and prove ownership.",
        status=status,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def get_review_records(db, claim_id):
    return db.scalars(
        select(ClaimReviewRecord).where(
            ClaimReviewRecord.claim_id == claim_id
        )
    ).all()


def test_review_claim_approves_and_records_review(db):
    found = make_report(db, "found", "Phone")
    claim = make_claim(db, found)

    result = review_claim(
        db, claim.id, "approved", "Ownership verified.", "reviewer-1"
    )

    assert result.status == "approved"

    records = get_review_records(db, claim.id)
    assert len(records) == 1
    assert records[0].decision == "approved"
    assert records[0].review_note == "Ownership verified."
    assert records[0].reviewer_label == "reviewer-1"


def test_review_claim_rejects_and_records_review(db):
    found = make_report(db, "found", "Phone")
    claim = make_claim(db, found)

    result = review_claim(
        db, claim.id, "rejected", "Insufficient proof.", "reviewer-1"
    )

    assert result.status == "rejected"

    records = get_review_records(db, claim.id)
    assert len(records) == 1
    assert records[0].decision == "rejected"


def test_review_claim_rejects_invalid_decision(db):
    with pytest.raises(ValueError, match="Decision must be"):
        review_claim(db, 1, "pending", "Some note", "reviewer-1")


def test_review_claim_rejects_missing_claim(db):
    with pytest.raises(ValueError, match="Claim not found"):
        review_claim(db, 99999, "approved", "Verified.", "reviewer-1")


def test_review_claim_rejects_non_pending_claim(db):
    found = make_report(db, "found", "Phone")
    claim = make_claim(db, found, status="rejected")

    with pytest.raises(ValueError, match="Only pending claims"):
        review_claim(db, claim.id, "approved", "Verified.", "reviewer-1")


def test_review_claim_rejects_inactive_found_report(db):
    found = make_report(db, "found", "Phone", status="returned")
    claim = make_claim(db, found)

    with pytest.raises(ValueError, match="no longer active"):
        review_claim(db, claim.id, "approved", "Verified.", "reviewer-1")


def test_approval_rejects_competing_pending_claims(db):
    found = make_report(db, "found", "Phone")
    first_claim = make_claim(db, found)
    second_claim = make_claim(db, found)

    result = review_claim(
        db, first_claim.id, "approved", "Proof verified.", "reviewer-1"
    )

    db.refresh(second_claim)

    assert result.status == "approved"
    assert second_claim.status == "rejected"

    first_records = get_review_records(db, first_claim.id)
    second_records = get_review_records(db, second_claim.id)

    assert len(first_records) == 1
    assert first_records[0].decision == "approved"
    assert len(second_records) == 1
    assert second_records[0].decision == "rejected"


def test_cannot_approve_another_claim_after_approval(db):
    found = make_report(db, "found", "Phone")
    first_claim = make_claim(db, found)
    second_claim = make_claim(db, found)

    review_claim(
        db, first_claim.id, "approved", "Proof verified.", "reviewer-1"
    )

    # Restore a pending competing claim to directly exercise the
    # service's existing-approval guard independently of auto-rejection.
    second_claim.status = "pending"
    db.commit()

    with pytest.raises(ValueError, match="already approved"):
        review_claim(
            db, second_claim.id, "approved", "Another proof.", "reviewer-2"
        )


def test_handover_completes_claim_and_returns_found_item(db):
    found = make_report(db, "found", "Phone")
    claim = make_claim(db, found, status="approved")

    result = complete_handover(
        db, claim.id, "Item returned to owner.", "reviewer-1"
    )

    db.refresh(found)

    assert result.status == "completed"
    assert found.status == "returned"

    handover = db.scalars(
        select(ClaimHandoverRecord).where(
            ClaimHandoverRecord.claim_id == claim.id
        )
    ).first()

    assert handover is not None
    assert handover.handover_note == "Item returned to owner."
    assert handover.reviewer_label == "reviewer-1"


def test_handover_rejects_missing_claim(db):
    with pytest.raises(ValueError, match="Claim not found"):
        complete_handover(db, 99999, "Item returned.", "reviewer-1")


def test_handover_rejects_unapproved_claim(db):
    found = make_report(db, "found", "Phone")
    claim = make_claim(db, found, status="pending")

    with pytest.raises(ValueError, match="Only approved claims"):
        complete_handover(db, claim.id, "Item returned.", "reviewer-1")


def test_handover_rejects_inactive_found_report(db):
    found = make_report(db, "found", "Phone", status="returned")
    claim = make_claim(db, found, status="approved")

    with pytest.raises(ValueError, match="no longer active"):
        complete_handover(db, claim.id, "Item returned.", "reviewer-1")


def test_handover_cannot_be_completed_twice(db):
    found = make_report(db, "found", "Phone")
    claim = make_claim(db, found, status="approved")

    complete_handover(db, claim.id, "First handover.", "reviewer-1")

    with pytest.raises(ValueError, match="Only approved claims"):
        complete_handover(db, claim.id, "Second handover.", "reviewer-1")
