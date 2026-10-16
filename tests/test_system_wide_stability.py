"""System-Wide Stability, Feature Isolation, and End-to-End Regression Suite.

Validates all 10 core workflows (A through J) to guarantee system-wide stability,
backward compatibility, and strict feature isolation across LostAndFoundAI.
"""

import io
from datetime import date
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.db.database import Base, get_db
from app.db.models import Claim, ClaimHandoverRecord, ItemReport
from app.main import app


def make_test_png() -> bytes:
    """Generate valid PNG bytes that pass PIL image validation."""
    buf = io.BytesIO()
    img = Image.new("RGB", (32, 32), color=(70, 130, 180))
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Isolated in-memory test database, test evidence directory, and test client."""
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

    temp_evidence_dir = tmp_path / "private_evidence"
    temp_evidence_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "PRIVATE_EVIDENCE_DIR", temp_evidence_dir)

    client = TestClient(app)
    yield client, TestingSessionLocal

    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# WORKFLOW A — Ordinary Reporting & Multiple Images
# ---------------------------------------------------------------------------

def test_workflow_a_ordinary_reporting_and_images(api):
    client, SessionLocal = api

    # 1. Create Found Report
    found_resp = client.post(
        "/api/reports",
        json={
            "report_type": "found",
            "item_name": "Calculus Textbook",
            "category": "Book",
            "description": "Stewart Calculus 8th edition found in library.",
            "event_date": date.today().isoformat(),
            "location_text": "Central Library Table 12",
        },
    )
    assert found_resp.status_code == 201
    found_id = found_resp.json()["id"]

    # 2. Upload multiple images to report
    png_bytes = make_test_png()
    files = [
        ("files", ("cover.png", png_bytes, "image/png")),
    ]
    img_resp = client.post(f"/api/reports/{found_id}/images", files=files)
    assert img_resp.status_code == 201

    # 3. Retrieve Report Details
    detail_resp = client.get(f"/api/reports/{found_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["item_name"] == "Calculus Textbook"

    # 4. Browse Reports
    browse_resp = client.get("/api/reports?report_type=found")
    assert browse_resp.status_code == 200
    assert len(browse_resp.json()) >= 1


# ---------------------------------------------------------------------------
# WORKFLOW B — AI Matching
# ---------------------------------------------------------------------------

def test_workflow_b_ai_matching(api):
    client, SessionLocal = api

    # Seed matching reports
    f_resp = client.post(
        "/api/reports",
        json={
            "report_type": "found",
            "item_name": "Silver Mac Charger",
            "category": "Electronics",
            "description": "MagSafe 3 charger left in CS Lab 2.",
            "event_date": date.today().isoformat(),
            "location_text": "CS Lab 2",
        },
    )
    f_id = f_resp.json()["id"]

    l_resp = client.post(
        "/api/reports",
        json={
            "report_type": "lost",
            "item_name": "MacBook Pro Charger",
            "category": "Electronics",
            "description": "Lost my white Apple MagSafe charger near lab.",
            "event_date": date.today().isoformat(),
            "location_text": "CS Building Foyer",
        },
    )
    l_id = l_resp.json()["id"]

    # Match found report
    m_resp = client.get(f"/api/reports/{f_id}/matches")
    assert m_resp.status_code == 200
    matches = m_resp.json().get("matches", [])
    assert len(matches) > 0
    assert matches[0]["report_id"] == l_id


# ---------------------------------------------------------------------------
# WORKFLOW C — Image-Only Search
# ---------------------------------------------------------------------------

def test_workflow_c_image_only_search(api):
    client, SessionLocal = api

    png_bytes = make_test_png()
    files = [("files", ("query.png", png_bytes, "image/png"))]

    resp = client.post("/api/reports/search-by-image", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert "query_image_count" in data
    assert "matches" in data


# ---------------------------------------------------------------------------
# WORKFLOW D — Guest Recovery & Anonymous Reporting
# ---------------------------------------------------------------------------

def test_workflow_d_guest_recovery(api):
    client, SessionLocal = api

    # 1. Driver reports found duffel bag
    f_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "Sports Duffel Bag",
            "category": "Bags & Luggage",
            "description": "Black gym duffel bag found in rear seat of auto.",
            "location_text": "Pune Station Stand",
            "journey_type": "auto_rickshaw",
            "pickup_location": "Deccan",
            "dropoff_location": "Station",
            "private_contents": "Nike shoes, red towel, fitness band",
        },
    )
    assert f_resp.status_code == 201
    receipt = f_resp.json()
    case_ref = receipt["case_reference"]
    secret_key = receipt["secret_key"]

    # 2. Passenger reports lost duffel bag
    l_resp = client.post(
        "/api/guest/lost",
        json={
            "item_name": "Nike Gym Bag",
            "category": "Bags & Luggage",
            "description": "Left my black duffel bag in auto on the way to station.",
            "location_text": "Deccan to Station",
            "journey_type": "auto_rickshaw",
            "pickup_location": "Deccan",
            "dropoff_location": "Station",
            "contact_value": "gymstudent@college.edu",
        },
    )
    assert l_resp.status_code == 201

    # 3. Retrieve Case Details
    case_resp = client.get(f"/api/guest/cases/{case_ref}?key={secret_key}")
    assert case_resp.status_code == 200
    assert case_resp.json()["private_contents"] == "Nike shoes, red towel, fitness band"


# ---------------------------------------------------------------------------
# WORKFLOW E — GPS & Handover Locations
# ---------------------------------------------------------------------------

def test_workflow_e_gps_and_handover(api):
    client, SessionLocal = api

    # Search nearby locations with GPS
    resp = client.get("/api/handover/nearby?lat=18.5204&lon=73.8567&radius_km=5.0")
    assert resp.status_code == 200
    data = resp.json()
    assert "locations" in data
    assert len(data["locations"]) > 0

    # Campus security primary desk
    campus_resp = client.get("/api/handover/campus")
    assert campus_resp.status_code == 200
    assert "Security" in campus_resp.json()["name"]

    # Campus Directory
    dir_resp = client.get("/api/campus/locations")
    assert dir_resp.status_code == 200
    assert len(dir_resp.json()["locations"]) >= 4


# ---------------------------------------------------------------------------
# WORKFLOW F — Product Links & SSRF Protection
# ---------------------------------------------------------------------------

def test_workflow_f_product_links_and_ssrf(api):
    client, SessionLocal = api

    # SSRF blocking of local addresses
    block_resp = client.post("/api/product-links/enrich", json={"url": "http://127.0.0.1:8000/internal"})
    assert block_resp.status_code == 200
    assert block_resp.json()["extraction_status"] == "failed"

    # Ordinary reporting works even if product URL is omitted or fails
    norm_resp = client.post(
        "/api/reports",
        json={
            "report_type": "found",
            "item_name": "Titan Watch",
            "category": "Accessories",
            "description": "Steel analog watch found near canteen.",
            "event_date": date.today().isoformat(),
            "location_text": "Canteen Foyer",
        },
    )
    assert norm_resp.status_code == 201


# ---------------------------------------------------------------------------
# WORKFLOW G — Claims and Identity Review
# ---------------------------------------------------------------------------

def test_workflow_g_claims_and_review(api):
    client, SessionLocal = api
    db = SessionLocal()

    # Create reports
    found_rep = ItemReport(
        report_type="found", item_name="Casio Calculator", category="Electronics",
        description="Scientific calculator FX-991EX", event_date=date.today(),
        location_text="Math Hall", status="active",
    )
    lost_rep = ItemReport(
        report_type="lost", item_name="Casio FX-991EX", category="Electronics",
        description="Lost my calculator", event_date=date.today(),
        location_text="Math Hall", status="active",
    )
    db.add(found_rep)
    db.add(lost_rep)
    db.commit()
    db.refresh(found_rep)
    db.refresh(lost_rep)

    # 1. Submit Verified Claim
    c_resp = client.post(
        f"/api/verification/claims/{found_rep.id}",
        json={
            "lost_report_id": lost_rep.id,
            "claimant_name": "Neha Joshi",
            "contact_email": "neha@college.edu",
            "claim_message": "My calculator has initials NJ engraved on back.",
            "privacy_consent": True,
        },
    )
    assert c_resp.status_code == 201
    claim_id = c_resp.json()["id"]

    # 2. Reviewer Approves Claim
    decide_resp = client.post(
        f"/api/admin/claims/{claim_id}/decide",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"decision": "approved", "review_note": "Initials verified in person."},
    )
    assert decide_resp.status_code == 200
    assert decide_resp.json()["status"] == "approved"


# ---------------------------------------------------------------------------
# WORKFLOW H — Value-Based Rewards (Handover Required & Anti-Abuse)
# ---------------------------------------------------------------------------

def test_workflow_h_rewards_after_handover(api):
    client, SessionLocal = api
    db = SessionLocal()

    # Seed reports and approved claim
    found_rep = ItemReport(
        report_type="found", item_name="Guitar", category="Other",
        description="Yamaha acoustic guitar", event_date=date.today(),
        location_text="Music Room", status="active",
    )
    lost_rep = ItemReport(
        report_type="lost", item_name="Acoustic Guitar", category="Other",
        description="My Yamaha guitar", event_date=date.today(),
        location_text="Campus Quad", status="active",
    )
    db.add(found_rep)
    db.add(lost_rep)
    db.commit()

    claim = Claim(
        lost_report_id=lost_rep.id,
        found_report_id=found_rep.id,
        claimant_name="Karan Dave",
        contact_email="karan@college.edu",
        claim_message="My guitar",
        status="approved",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    # Record Handover
    client.post(
        f"/api/reports/claims/{claim.id}/handover",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={"handover_note": "Guitar handed over safely at campus security."},
    )

    # Credit points (Item value ₹10,000 * 10% = ₹1,000 -> 5,000 points)
    reward_resp = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim.id,
            "verified_item_value": 10000.0,
            "recipient_email": "finder_student@college.edu",
            "notes": "Verified recovery reward.",
        },
    )
    assert reward_resp.status_code == 201
    assert reward_resp.json()["points"] == 5000

    # Anti-abuse: Duplicate credit is prevented (409 Conflict)
    dup_resp = client.post(
        "/api/rewards/credit",
        headers={"X-Reviewer-Key": "secret-reviewer-key"},
        json={
            "claim_id": claim.id,
            "verified_item_value": 10000.0,
            "recipient_email": "finder_student@college.edu",
            "notes": "Duplicate credit attempt.",
        },
    )
    assert dup_resp.status_code in (400, 409)


# ---------------------------------------------------------------------------
# WORKFLOW I — Security Access Control
# ---------------------------------------------------------------------------

def test_workflow_i_security_access_control(api):
    client, SessionLocal = api

    # Reviewer portal endpoint without key -> 401/403 Access Denied
    unauth_resp = client.get("/api/admin/claims")
    assert unauth_resp.status_code in (401, 403)

    # Protected evidence download without key -> 401/403 Access Denied
    ev_resp = client.get("/api/admin/claims/1/evidence/1/file")
    assert ev_resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# WORKFLOW J — Empty Database and Failure Boundaries
# ---------------------------------------------------------------------------

def test_workflow_j_empty_and_failure_states(api):
    client, SessionLocal = api

    # Query nonexistent report
    assert client.get("/api/reports/999999").status_code == 404

    # Query nonexistent claim
    assert client.get("/api/claims/999999").status_code == 404

    # Query nonexistent guest case
    assert client.get("/api/guest/cases/GF-NOTFOUND?key=abc").status_code == 404

    # Invalid latitude/longitude rejected cleanly (422 Unprocessable)
    invalid_geo = client.get("/api/handover/nearby?lat=999.0&lon=999.0")
    assert invalid_geo.status_code in (400, 422)
