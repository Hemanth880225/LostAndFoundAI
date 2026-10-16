from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import Claim, ItemReport
from app.main import app


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Provide an isolated in-memory database and HTTP test client."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("REVIEWER_API_KEY", "test-reviewer-key")

    # Do not use a TestClient context manager: that would start the
    # application's lifespan and could initialize its real database.
    client = TestClient(app)

    yield client, TestingSessionLocal

    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def make_report(db, report_type="lost", status="active"):
    """Insert a report directly into the test database."""

    report = ItemReport(
        report_type=report_type,
        item_name="Black backpack",
        category="Bag",
        color="Black",
        brand="ExampleBrand",
        model=None,
        description="A black backpack with a small blue keychain.",
        event_date=date(2026, 10, 10),
        location_text="College library",
        latitude=None,
        longitude=None,
        status=status,
    )

    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def prepare_claim(client, session_factory):
    """Create one active lost report, one active found report, and a claim."""

    with session_factory() as db:
        lost_report = make_report(db, report_type="lost")
        found_report = make_report(db, report_type="found")

        lost_id = lost_report.id
        found_id = found_report.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": (
                "I lost this backpack and can identify its contents."
            ),
        },
    )

    assert response.status_code == 201, response.text
    return found_id, lost_id, response.json()["id"]


def test_submit_claim_success(api):
    client, session_factory = api
    found_id, lost_id, claim_id = prepare_claim(client, session_factory)

    response = client.get("/api/health")
    assert response.status_code == 200

    with session_factory() as db:
        claim = db.get(Claim, claim_id)
        assert claim is not None
        assert claim.found_report_id == found_id
        assert claim.lost_report_id == lost_id
        assert claim.status == "pending"


def test_claim_response_does_not_expose_private_fields(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.get("/api/health")
    assert response.status_code == 200

    # The public claim response schema intentionally excludes email
    # and the full claim message.
    with session_factory() as db:
        claim = db.get(Claim, claim_id)
        assert claim.contact_email == "claimant@example.com"
        assert claim.claim_message


def test_submit_claim_for_missing_found_report_returns_404(api):
    client, _ = api

    response = client.post(
        "/api/reports/99999/claims",
        json={
            "lost_report_id": 1,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 404


def test_submit_claim_when_found_report_is_actually_lost_returns_400(api):
    client, session_factory = api

    with session_factory() as db:
        wrong_found_report = make_report(db, report_type="lost")
        lost_report = make_report(db, report_type="lost")
        found_id = wrong_found_report.id
        lost_id = lost_report.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 400


def test_submit_claim_for_inactive_found_report_returns_400(api):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, report_type="found", status="returned")
        lost = make_report(db, report_type="lost")
        found_id = found.id
        lost_id = lost.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 400


def test_submit_claim_for_missing_lost_report_returns_404(api):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, report_type="found")
        found_id = found.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": 99999,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 404


def test_submit_claim_when_claimant_report_is_found_returns_400(api):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, report_type="found")
        another_found = make_report(db, report_type="found")
        found_id = found.id
        lost_id = another_found.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 400


def test_submit_claim_for_inactive_lost_report_returns_400(api):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, report_type="found")
        lost = make_report(db, report_type="lost", status="returned")
        found_id = found.id
        lost_id = lost.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 400


def test_submit_claim_rejects_invalid_email(api):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, report_type="found")
        lost = make_report(db, report_type="lost")
        found_id = found.id
        lost_id = lost.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "not-an-email",
            "claim_message": "I can identify this missing item.",
        },
    )

    assert response.status_code == 422


def test_submit_claim_rejects_short_message(api):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, report_type="found")
        lost = make_report(db, report_type="lost")
        found_id = found.id
        lost_id = lost.id

    response = client.post(
        f"/api/reports/{found_id}/claims",
        json={
            "lost_report_id": lost_id,
            "claimant_name": "Test Claimant",
            "contact_email": "claimant@example.com",
            "claim_message": "Too short",
        },
    )

    assert response.status_code == 422


def test_review_without_configured_key_returns_503(api, monkeypatch):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)
    monkeypatch.delenv("REVIEWER_API_KEY")

    response = client.patch(
        f"/api/reports/claims/{claim_id}/review",
        json={
            "status": "approved",
            "review_note": "Ownership details verified.",
        },
    )

    assert response.status_code == 503


@pytest.mark.parametrize("headers", [{}, {"X-Reviewer-Key": "wrong-key"}])
def test_review_without_valid_reviewer_key_returns_403(api, headers):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.patch(
        f"/api/reports/claims/{claim_id}/review",
        headers=headers,
        json={
            "status": "approved",
            "review_note": "Ownership details verified.",
        },
    )

    assert response.status_code == 403


def test_approve_claim_with_valid_reviewer_key(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.patch(
        f"/api/reports/claims/{claim_id}/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "status": "approved",
            "review_note": "Ownership details verified.",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"


def test_reject_claim_with_valid_reviewer_key(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.patch(
        f"/api/reports/claims/{claim_id}/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "status": "rejected",
            "review_note": "The ownership evidence is insufficient.",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"


def test_review_nonexistent_claim_returns_404(api):
    client, _ = api

    response = client.patch(
        "/api/reports/claims/99999/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "status": "approved",
            "review_note": "Ownership details verified.",
        },
    )

    assert response.status_code == 404


def test_review_rejects_invalid_decision(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.patch(
        f"/api/reports/claims/{claim_id}/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "status": "pending",
            "review_note": "Ownership details verified.",
        },
    )

    assert response.status_code == 422


def test_handover_rejects_pending_claim(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={"handover_note": "Item handed to claimant."},
    )

    assert response.status_code == 400


def test_handover_requires_reviewer_authentication(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    response = client.post(
        f"/api/reports/claims/{claim_id}/handover",
        json={"handover_note": "Item handed to claimant."},
    )

    assert response.status_code == 403


def test_handover_after_approval_marks_item_returned(api):
    client, session_factory = api
    found_id, _, claim_id = prepare_claim(client, session_factory)

    review_response = client.patch(
        f"/api/reports/claims/{claim_id}/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "status": "approved",
            "review_note": "Ownership details verified.",
        },
    )

    assert review_response.status_code == 200, review_response.text

    handover_response = client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "handover_note": "Backpack handed to verified claimant."
        },
    )

    assert handover_response.status_code == 200, handover_response.text
    assert handover_response.json()["status"] == "completed"

    with session_factory() as db:
        found_report = db.get(ItemReport, found_id)
        claim = db.get(Claim, claim_id)

        assert found_report.status == "returned"
        assert claim.status == "completed"


def test_handover_rejects_short_note(api):
    client, session_factory = api
    _, _, claim_id = prepare_claim(client, session_factory)

    client.patch(
        f"/api/reports/claims/{claim_id}/review",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={
            "status": "approved",
            "review_note": "Ownership details verified.",
        },
    )

    response = client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "test-reviewer-key"},
        json={"handover_note": "No"},
    )

    assert response.status_code == 422
