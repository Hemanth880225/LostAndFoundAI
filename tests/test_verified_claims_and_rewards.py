"""Automated test suite for Verified Claims, Identity Review, Fraud Escalation, and Value-Based Reward Points."""

import io
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.db.database import Base, get_db
from app.db.models import (
    Claim,
    ClaimEvidence,
    ClaimHandoverRecord,
    ClaimVerificationDetail,
    EvidenceAuditLog,
    ItemReport,
    PoliceComplaintDraft,
    RewardLedger,
)
from app.extensions.claims_verification.schemas import VerificationStatus
from app.extensions.rewards.ledger import calculate_points
from app.main import app


# ---------------------------------------------------------------------------
# Test Database Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch, tmp_path):
    """Provide an isolated in-memory test database, temp evidence dir, and test client."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("REVIEWER_API_KEY", "secret-reviewer-key")

    # Point private evidence storage to a temporary directory
    temp_evidence_dir = tmp_path / "private_evidence"
    temp_evidence_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "PRIVATE_EVIDENCE_DIR", temp_evidence_dir)

    client = TestClient(app)
    yield client, TestingSessionLocal, temp_evidence_dir

    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def seed_reports(db):
    """Helper to seed active found and lost reports."""
    found = ItemReport(
        report_type="found",
        item_name="Silver Dell XPS 15",
        category="Electronics",
        description="Found in lecture hall 3, has a metallic case.",
        event_date=date(2026, 10, 10),
        location_text="Lecture Hall 3",
        status="active",
    )
    lost = ItemReport(
        report_type="lost",
        item_name="Dell XPS Laptop",
        category="Electronics",
        description="Lost my Dell laptop near lecture hall.",
        event_date=date(2026, 10, 10),
        location_text="Lecture Complex",
        status="active",
    )
    db.add(found)
    db.add(lost)
    db.commit()
    db.refresh(found)
    db.refresh(lost)
    return found, lost


# ---------------------------------------------------------------------------
# FEATURE 1: Verified Claim Submission & Evidence Handling
# ---------------------------------------------------------------------------

def test_valid_verified_claim_submission(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    payload = {
        "lost_report_id": lost.id,
        "claimant_name": "Arjun Sharma",
        "contact_email": "arjun@college.edu",
        "contact_phone": "+91 98765 43210",
        "claim_message": "This is my Dell laptop with serial number sticker on back.",
        "serial_number": "DELL-XPS-9520-SN123",
        "identifying_features": "Scratch near right USB port",
        "distinctive_marks": "Small Linux penguin sticker on top lid",
        "privacy_consent": True,
    }

    resp = client.post(f"/api/verification/claims/{found.id}", json=payload)
    assert resp.status_code == 201
    data = resp.json()

    assert data["claimant_name"] == "Arjun Sharma"
    assert data["contact_email"] == "arjun@college.edu"
    assert data["phone_verified"] is False
    assert data["email_verified"] is False
    assert data["verification_method"] == "unverified"
    assert data["verification_status"] == "submitted"
    assert "queued for reviewer" in data["public_status_message"].lower()

    # Verify audit log
    claim_id = data["id"]
    audit = db.query(EvidenceAuditLog).filter(EvidenceAuditLog.claim_id == claim_id).first()
    assert audit is not None
    assert audit.action == "CLAIM_SUBMITTED"


def test_claim_submission_missing_privacy_consent_rejected(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    payload = {
        "lost_report_id": lost.id,
        "claimant_name": "Arjun Sharma",
        "contact_email": "arjun@college.edu",
        "claim_message": "This is my laptop.",
        "privacy_consent": False,  # Missing consent
    }

    resp = client.post(f"/api/verification/claims/{found.id}", json=payload)
    assert resp.status_code == 400
    assert "consent" in resp.json()["detail"].lower()


def test_upload_ownership_evidence_to_private_storage(api):
    client, SessionLocal, evidence_dir = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    # Submit claim first
    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Priya Patel",
            "contact_email": "priya@college.edu",
            "claim_message": "I lost this laptop on campus yesterday.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    # Upload PDF purchase receipt
    fake_pdf = io.BytesIO(b"%PDF-1.4 Fake invoice content for laptop purchase")
    files = {"file": ("invoice.pdf", fake_pdf, "application/pdf")}
    data = {
        "evidence_type": "purchase_receipt",
        "description": "Original Amazon purchase invoice",
        "is_sensitive": "false",
    }

    resp = client.post(f"/api/verification/claims/{claim_id}/evidence", data=data, files=files)
    assert resp.status_code == 201
    ev_data = resp.json()

    assert ev_data["evidence_type"] == "purchase_receipt"
    assert ev_data["original_filename"] == "invoice.pdf"

    # Verify file is in private evidence dir, not public uploads
    saved_files = list(evidence_dir.glob("*.pdf"))
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes().startswith(b"%PDF-1.4")


def test_evidence_file_access_restricted_to_reviewers(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Priya Patel",
            "contact_email": "priya@college.edu",
            "claim_message": "Laptop claim with invoice.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    files = {"file": ("receipt.png", io.BytesIO(b"\x89PNG\r\n\x1a\nfakeimagebytes"), "image/png")}
    ev_resp = client.post(
        f"/api/verification/claims/{claim_id}/evidence",
        data={"evidence_type": "purchase_receipt", "description": "Receipt"},
        files=files,
    )
    evidence_id = ev_resp.json()["id"]

    # Unauthorized access (no reviewer key) -> 403 / 503
    unauth_resp = client.get(f"/api/admin/claims/{claim_id}/evidence/{evidence_id}/file")
    assert unauth_resp.status_code in [403, 503]

    # Authorized reviewer access -> 200 OK
    auth_resp = client.get(
        f"/api/admin/claims/{claim_id}/evidence/{evidence_id}/file",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
    )
    assert auth_resp.status_code == 200
    assert auth_resp.content.startswith(b"\x89PNG")


# ---------------------------------------------------------------------------
# FEATURE 3: Reviewer Workflow & Additional Information Requests
# ---------------------------------------------------------------------------

def test_reviewer_requests_additional_information(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Rohan Mehra",
            "contact_email": "rohan@college.edu",
            "claim_message": "Lost silver laptop in lecture hall 3.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    # Reviewer requests clarifying serial number
    inquiry_resp = client.post(
        f"/api/admin/claims/{claim_id}/request-info",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"request_note": "Please specify the exact Dell model or provide the charger wattage."},
    )
    assert inquiry_resp.status_code == 200
    assert inquiry_resp.json()["verification_status"] == "additional_information_required"

    # Public claim status reflects action required
    status_resp = client.get(f"/api/verification/claims/{claim_id}/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["verification_status"] == "additional_information_required"
    assert "charger wattage" in status_resp.json()["additional_info_requested"]

    # Claimant responds with additional information
    resp_info = client.post(
        f"/api/verification/claims/{claim_id}/additional-info",
        json={"additional_info": "The charger is a 130W USB-C brick with a black velcro tie."},
    )
    assert resp_info.status_code == 200
    assert resp_info.json()["verification_status"] == "under_review"


def test_reviewer_approval_and_rejection_paths(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Rohan Mehra",
            "contact_email": "rohan@college.edu",
            "claim_message": "Laptop with matching stickers.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    # Approve claim
    approve_resp = client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "approved", "review_note": "Ownership verified via charger and serial match."},
    )
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"

    # Cannot re-review already approved claim
    re_review = client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "rejected", "review_note": "Changed mind."},
    )
    assert re_review.status_code == 400


# ---------------------------------------------------------------------------
# FEATURE 4: Fraud Escalation & Police Complaint Draft Generation
# ---------------------------------------------------------------------------

def test_fraud_escalation_and_police_complaint_draft(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Suspicious Actor",
            "contact_email": "suspicious@temp.com",
            "claim_message": "I own this device.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    # Flag for suspected fraud
    flag_resp = client.post(
        f"/api/admin/claims/{claim_id}/flag-fraud",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"fraud_reason": "Claimant submitted altered invoice with mismatched fonts; serial belongs to another report."},
    )
    assert flag_resp.status_code == 200
    assert flag_resp.json()["verification_status"] == "suspected_fraud_review"

    # Verify public status does NOT publicly defame or expose fraud label
    pub_resp = client.get(f"/api/verification/claims/{claim_id}/status")
    assert "fraudster" not in pub_resp.json()["public_status_message"].lower()

    # Generate Police Complaint Draft
    draft_resp = client.post(
        f"/api/admin/claims/{claim_id}/police-draft",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"target_station": "Shivajinagar Police Station, Pune"},
    )
    assert draft_resp.status_code == 200
    draft_data = draft_resp.json()

    assert draft_data["draft_reference"].startswith(f"PCD-{claim_id}-")
    assert draft_data["status"] == "draft_pending_human_submission"
    assert "Shivajinagar Police Station" in draft_data["police_station_target"]
    assert "Found report" in draft_data["event_timeline"]
    assert "Suspicious Actor" in draft_data["shareable_contact_info"]


# ---------------------------------------------------------------------------
# FEATURE 5 & 6: Value-Based Reward Points & Auditable Ledger
# ---------------------------------------------------------------------------

def test_reward_points_conversion_and_caps():
    """Verify 5 points = ₹1 formula with minimum ₹50 and maximum ₹2,000 caps."""
    # ₹2,500 item * 10% = ₹250. 250 * 5 = 1,250 points
    rupees, points, is_capped, _ = calculate_points(item_value=2500.0)
    assert rupees == 250.0
    assert points == 1250
    assert is_capped is False

    # Low value: ₹200 item * 10% = ₹20 -> clamped to minimum ₹50. 50 * 5 = 250 points
    rupees_low, points_low, _, _ = calculate_points(item_value=200.0)
    assert rupees_low == 50.0
    assert points_low == 250

    # High value: ₹50,000 item * 10% = ₹5,000 -> clamped to maximum ₹2,000 cap. 2000 * 5 = 10,000 points
    rupees_high, points_high, is_capped_high, cap_val = calculate_points(item_value=50000.0)
    assert rupees_high == 2000.0
    assert points_high == 10000
    assert is_capped_high is True
    assert cap_val == 2000.0


def test_no_points_awarded_before_completed_handover(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Dev Patel",
            "contact_email": "dev@college.edu",
            "claim_message": "My lost laptop.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    # Attempt to credit reward while claim is still pending -> 400 Bad Request
    reward_resp = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim_id,
            "verified_item_value": 30000.0,
            "recipient_email": "finder@college.edu",
            "notes": "Premature credit attempt",
        },
    )
    assert reward_resp.status_code == 400
    assert "handover" in reward_resp.json()["detail"].lower()


def test_rewards_credited_after_verified_handover(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    # 1. Submit claim
    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Dev Patel",
            "contact_email": "dev@college.edu",
            "claim_message": "My lost laptop.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    # 2. Reviewer approves claim
    client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "approved", "review_note": "Verified ownership."},
    )

    # 3. Core handover completed
    client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"handover_note": "Handed over at campus security command desk."},
    )

    # 4. Credit reward to finder
    # ₹10,000 item * 10% = ₹1,000. 1000 * 5 = 5,000 points
    reward_resp = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim_id,
            "verified_item_value": 10000.0,
            "recipient_email": "honest_finder@college.edu",
            "recipient_name": "Rahul Verma",
            "notes": "Verified laptop return; student integrity recognition.",
        },
    )
    assert reward_resp.status_code == 201
    entry = reward_resp.json()
    assert entry["points"] == 5000
    assert entry["reward_rupees"] == 1000.0
    assert entry["transaction_type"] == "recovery_reward"

    # 5. Check finder's balance
    bal_resp = client.get("/api/rewards/balance/honest_finder@college.edu")
    assert bal_resp.status_code == 200
    bal_data = bal_resp.json()
    assert bal_data["total_points"] == 5000
    assert bal_data["estimated_programme_value_rupees"] == 1000.0
    assert bal_data["approved_rewards_count"] == 1
    assert len(bal_data["transactions"]) == 1


def test_anti_abuse_duplicate_reward_prevention(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Dev Patel",
            "contact_email": "dev@college.edu",
            "claim_message": "Laptop recovery.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "approved", "review_note": "Verified."},
    )
    client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"handover_note": "Handed over."},
    )

    # First reward credit succeeds
    res1 = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim_id,
            "verified_item_value": 5000.0,
            "recipient_email": "finder@college.edu",
            "notes": "First reward award",
        },
    )
    assert res1.status_code == 201

    # Second reward credit for same recovery fails with 409 Conflict
    res2 = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim_id,
            "verified_item_value": 5000.0,
            "recipient_email": "finder@college.edu",
            "notes": "Duplicate credit attempt",
        },
    )
    assert res2.status_code == 409


def test_anti_abuse_claimant_cannot_self_award(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Dev Patel",
            "contact_email": "claimant@college.edu",
            "claim_message": "Laptop claim.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "approved", "review_note": "Verified."},
    )
    client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"handover_note": "Handed over."},
    )

    # Claimant trying to award themselves finder points fails with 400
    res = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim_id,
            "verified_item_value": 5000.0,
            "recipient_email": "claimant@college.edu",  # Same as claimant email!
            "notes": "Self reward attempt",
        },
    )
    assert res.status_code == 400
    assert "self-awarding" in res.json()["detail"].lower()


def test_reward_reversal_creates_offsetting_ledger_transaction(api):
    client, SessionLocal, _ = api
    db = SessionLocal()
    found, lost = seed_reports(db)

    c_resp = client.post(
        f"/api/verification/claims/{found.id}",
        json={
            "lost_report_id": lost.id,
            "claimant_name": "Dev Patel",
            "contact_email": "dev@college.edu",
            "claim_message": "Laptop claim.",
            "privacy_consent": True,
        },
    )
    claim_id = c_resp.json()["id"]

    client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "approved", "review_note": "Verified."},
    )
    client.post(
        f"/api/reports/claims/{claim_id}/handover",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"handover_note": "Handed over."},
    )

    cred = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim_id,
            "verified_item_value": 2000.0,
            "recipient_email": "student_finder@college.edu",
            "notes": "Credit to be reversed",
        },
    ).json()
    tx_id = cred["transaction_id"]

    # Perform reversal
    rev_resp = client.post(
        "/api/rewards/reverse",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"transaction_id": tx_id, "reason": "Valuation error or erroneous credit"},
    )
    assert rev_resp.status_code == 200
    rev_data = rev_resp.json()
    assert rev_data["transaction_type"] == "reversal"
    assert rev_data["points"] == -cred["points"]  # Negative points

    # Balance after reversal is 0
    bal = client.get("/api/rewards/balance/student_finder@college.edu").json()
    assert bal["total_points"] == 0
    assert bal["estimated_programme_value_rupees"] == 0.0


# ---------------------------------------------------------------------------
# Frontend Views & Route Rendering Tests
# ---------------------------------------------------------------------------

def test_claim_status_page_renders(api):
    client, _, _ = api
    resp = client.get("/claims/1")
    assert resp.status_code == 200
    assert "CLAIM VERIFICATION PORTAL" in resp.text
    assert "claim-status.js" in resp.text


def test_admin_review_page_renders(api):
    client, _, _ = api
    resp = client.get("/admin/review")
    assert resp.status_code == 200
    assert "Claim Verification & Recovery Review" in resp.text
    assert "admin-review.js" in resp.text


def test_rewards_programme_page_renders(api):
    client, _, _ = api
    resp = client.get("/rewards")
    assert resp.status_code == 200
    assert "Value-Based Reward Points" in resp.text
    assert "rewards.js" in resp.text
    assert "5 reward points = ₹1" in resp.text
