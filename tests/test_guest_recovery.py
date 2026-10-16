"""Comprehensive automated test suite for Guest Finder, Anonymous Reporting, and Transit Recovery."""

import io
from datetime import date, datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.db.database import Base, get_db
from app.db.models import (
    Claim,
    ClaimHandoverRecord,
    GuestCoordinationMessage,
    GuestHandoverVerification,
    GuestRecoveryReport,
    ItemReport,
    RewardLedger,
)
from app.extensions.guest_recovery.matching import find_guest_matches, score_guest_candidate
from app.extensions.guest_recovery.qr import generate_qr_svg, build_transit_destination_url
from app.main import app


# ---------------------------------------------------------------------------
# Test Database Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def api(monkeypatch, tmp_path):
    """Provide an isolated in-memory test database and client."""
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

    client = TestClient(app)
    yield client, TestingSessionLocal, tmp_path

    client.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ---------------------------------------------------------------------------
# FEATURE 1: Guest "I Found an Item" Workflow
# ---------------------------------------------------------------------------

def test_guest_found_submission_without_account(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    payload = {
        "item_name": "Blue Clothes Bag",
        "category": "Bags & Luggage",
        "description": "Cloth duffel bag left on the back seat.",
        "color": "Navy Blue",
        "brand": "Generic",
        "location_text": "Pune Railway Station Auto Stand",
        "journey_type": "auto_rickshaw",
        "pickup_location": "Deccan Gymkhana",
        "dropoff_location": "Pune Railway Station",
        "vehicle_identifier": "MH 12 AB 9999",
        "private_contents": "Three shirts, blue towel, prescription glasses",
        "distinctive_marks": "Small red ribbon on zipper",
        "is_anonymous": False,
        "contact_method": "phone",
        "contact_value": "9876543210",
    }

    resp = client.post("/api/guest/found", json=payload)
    assert resp.status_code == 201
    receipt = resp.json()

    # 1. Verify secure case reference and key
    assert receipt["case_reference"].startswith("GF-")
    assert len(receipt["secret_key"]) >= 32
    assert receipt["guest_role"] == "finder"
    assert receipt["is_anonymous"] is False
    assert "/guest/case/" in receipt["tracking_url"]
    assert "SAFETY ADVISORY" in receipt["safety_guidance"]

    # 2. Verify database records
    report_id = receipt["report_id"]
    report = db.get(ItemReport, report_id)
    assert report is not None
    assert report.report_type == "found"
    assert report.status == "active"
    assert report.item_name == "Blue Clothes Bag"

    # 3. Verify private metadata isolation
    meta = db.scalars(
        select(GuestRecoveryReport).where(GuestRecoveryReport.report_id == report_id)
    ).first()
    assert meta is not None
    assert meta.private_contents == "Three shirts, blue towel, prescription glasses"
    assert meta.distinctive_marks == "Small red ribbon on zipper"
    assert meta.contact_value == "9876543210"


def test_anonymous_finder_submission_omits_contact_and_advises_safe_handover(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    payload = {
        "item_name": "Black Umbrella",
        "category": "Personal Items",
        "description": "Found inside auto near Swargate.",
        "location_text": "Swargate Auto Stand",
        "journey_type": "auto_rickshaw",
        "is_anonymous": True,
        "contact_method": "none",
        "contact_value": "should_be_ignored@temp.com",
    }

    resp = client.post("/api/guest/found", json=payload)
    assert resp.status_code == 201
    receipt = resp.json()

    assert receipt["is_anonymous"] is True

    # Contact value must be stripped for anonymous submission
    meta = db.scalars(
        select(GuestRecoveryReport).where(GuestRecoveryReport.case_reference == receipt["case_reference"])
    ).first()
    assert meta.is_anonymous is True
    assert meta.contact_value is None

    # Check initial system advice in messages
    msg = db.scalars(
        select(GuestCoordinationMessage).where(GuestCoordinationMessage.guest_report_id == meta.id)
    ).first()
    assert msg is not None
    assert "anonymous" in msg.message_text.lower()
    assert "official" in msg.message_text.lower()


# ---------------------------------------------------------------------------
# FEATURE 2: Guest "I Lost an Item" Workflow
# ---------------------------------------------------------------------------

def test_guest_lost_submission_without_driver_info(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    payload = {
        "item_name": "Blue Duffel Bag",
        "category": "Bags & Luggage",
        "description": "Left my clothes bag in an auto travelling to railway station.",
        "location_text": "En route from Deccan to Pune Station",
        "journey_type": "auto_rickshaw",
        "pickup_location": "Deccan",
        "dropoff_location": "Pune Railway Station",
        "approximate_time": "10:00 AM",
        "private_contents": "Three cotton shirts, prescription spectacles",
        "distinctive_marks": "Red thread attached to zipper",
        "contact_method": "email",
        "contact_value": "passenger@college.edu",
    }

    resp = client.post("/api/guest/lost", json=payload)
    assert resp.status_code == 201
    receipt = resp.json()

    assert receipt["case_reference"].startswith("GL-")
    assert receipt["guest_role"] == "passenger"

    report = db.get(ItemReport, receipt["report_id"])
    assert report is not None
    assert report.report_type == "lost"
    assert report.status == "active"


# ---------------------------------------------------------------------------
# FEATURE 3: Protection of Ownership Details (Public vs Private)
# ---------------------------------------------------------------------------

def test_private_versus_public_report_fields(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    # Create found report with private contents
    c_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "Clothes Bag",
            "category": "Bags & Luggage",
            "description": "Public exterior description of bag.",
            "location_text": "Station Stand",
            "private_contents": "Extremely secret documents and expensive jewelry",
            "distinctive_marks": "Secret serial etched on buckle: SN-9988",
            "contact_method": "phone",
            "contact_value": "+91 99999 11111",
        },
    )
    receipt = c_resp.json()
    rep_id = receipt["report_id"]
    case_ref = receipt["case_reference"]
    secret_key = receipt["secret_key"]

    # 1. Test Public View: Private details MUST be omitted
    pub_resp = client.get(f"/api/guest/reports/{rep_id}/safe")
    assert pub_resp.status_code == 200
    pub_data = pub_resp.json()

    assert pub_data["item_name"] == "Clothes Bag"
    assert pub_data["description"] == "Public exterior description of bag."
    assert "private_contents" not in pub_data
    assert "distinctive_marks" not in pub_data
    assert "Extremely secret" not in str(pub_data)
    assert "SN-9988" not in str(pub_data)
    assert "+91 99999" not in str(pub_data)

    # 2. Accessing Case Dossier without Secret Key -> 401 Unauthorized
    unauth_resp = client.get(f"/api/guest/cases/{case_ref}")
    assert unauth_resp.status_code == 401

    # 3. Accessing Case Dossier with Secret Key -> 200 with Private Details
    auth_resp = client.get(f"/api/guest/cases/{case_ref}?key={secret_key}")
    assert auth_resp.status_code == 200
    auth_data = auth_resp.json()
    assert auth_data["private_contents"] == "Extremely secret documents and expensive jewelry"
    assert auth_data["distinctive_marks"] == "Secret serial etched on buckle: SN-9988"


# ---------------------------------------------------------------------------
# FEATURE 4: Journey & Time Matching (Treats Unknowns as Unknown, Not Mismatches)
# ---------------------------------------------------------------------------

def test_matching_when_gps_coordinates_are_missing(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    # 1. Found report with no GPS (lat=None, lon=None)
    f_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "Brown Leather Wallet",
            "category": "Documents & Wallets",
            "description": "Found on seat in auto rickshaw.",
            "location_text": "Pune Station",
            "latitude": None,
            "longitude": None,
            "journey_type": "auto_rickshaw",
            "pickup_location": "Swargate",
            "dropoff_location": "Station",
        },
    )
    found_id = f_resp.json()["report_id"]

    # 2. Lost report with no GPS
    l_resp = client.post(
        "/api/guest/lost",
        json={
            "item_name": "Brown Leather Wallet",
            "category": "Documents & Wallets",
            "description": "Lost my leather wallet during auto ride.",
            "location_text": "En route to Pune Station",
            "latitude": None,
            "longitude": None,
            "journey_type": "auto_rickshaw",
            "pickup_location": "Swargate",
            "dropoff_location": "Station",
            "contact_value": "user@college.edu",
        },
    )
    lost_id = l_resp.json()["report_id"]

    # 3. Match found report against candidates
    matches_resp = client.get(f"/api/guest/matches/{found_id}")
    assert matches_resp.status_code == 200
    matches = matches_resp.json()

    assert len(matches) > 0
    top_match = matches[0]
    assert top_match["candidate_report_id"] == lost_id
    assert top_match["score"] >= 60.0
    assert "journey" in top_match["components"]
    assert top_match["journey_context"]["journey_compatible"] is True


def test_incomplete_route_and_time_information_handled_resiliently(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    # Found report with completely missing route, vehicle id, and time
    f_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "Titan Wristwatch",
            "category": "Personal Items",
            "description": "Found watch left on bench.",
            "location_text": "Transit Lounge",
            "pickup_location": None,
            "dropoff_location": None,
            "approximate_time": None,
            "journey_type": None,
        },
    )
    found_id = f_resp.json()["report_id"]

    l_resp = client.post(
        "/api/guest/lost",
        json={
            "item_name": "Titan Steel Watch",
            "category": "Personal Items",
            "description": "Lost my silver Titan watch.",
            "location_text": "Transit Lounge Area",
            "contact_value": "watchowner@college.edu",
        },
    )
    lost_id = l_resp.json()["report_id"]

    # Must calculate score without crashing or throwing zero-division
    matches_resp = client.get(f"/api/guest/matches/{found_id}")
    assert matches_resp.status_code == 200
    matches = matches_resp.json()
    assert len(matches) > 0
    assert matches[0]["candidate_report_id"] == lost_id


# ---------------------------------------------------------------------------
# FEATURE 5: Privacy-Preserving Coordination Channel
# ---------------------------------------------------------------------------

def test_masked_coordination_messages_between_parties(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    f_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "College Backpack",
            "category": "Bags & Luggage",
            "description": "Black bag found in auto.",
            "location_text": "Station Stand",
            "contact_method": "phone",
            "contact_value": "9876543210",
        },
    )
    receipt = f_resp.json()
    case_ref = receipt["case_reference"]
    secret_key = receipt["secret_key"]

    # Post message as finder
    msg_resp = client.post(
        f"/api/guest/cases/{case_ref}/messages?key={secret_key}",
        json={"message_text": "Hello, I have deposited the bag safely. Are you near the station?", "is_safe_location_suggestion": True},
    )
    assert msg_resp.status_code == 200
    msg_data = msg_resp.json()
    assert msg_data["sender_role"] == "finder"
    assert msg_data["is_safe_location_suggestion"] is True

    # Retrieve case messages
    case_resp = client.get(f"/api/guest/cases/{case_ref}?key={secret_key}")
    messages = case_resp.json()["messages"]
    assert len(messages) >= 2  # Initial system message + finder message
    assert any("near the station" in m["message_text"] for m in messages)


# ---------------------------------------------------------------------------
# FEATURE 6: Safe Handover Code & Confirmation
# ---------------------------------------------------------------------------

def test_safe_handover_code_generation_and_completion(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    # 1. Create found report
    f_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "HP Laptop Charger",
            "category": "Electronics",
            "description": "Blue tip 65W charger found in cab.",
            "location_text": "Pune Station",
        },
    )
    receipt = f_resp.json()
    case_ref = receipt["case_reference"]
    secret_key = receipt["secret_key"]
    found_id = receipt["report_id"]

    # 2. Seed an associated approved Claim
    lost_rep = ItemReport(
        report_type="lost",
        item_name="HP Laptop Charger",
        category="Electronics",
        description="Lost charger in taxi",
        event_date=date(2026, 10, 10),
        location_text="Pune Station",
        status="active",
    )
    db.add(lost_rep)
    db.commit()
    db.refresh(lost_rep)

    claim = Claim(
        lost_report_id=lost_rep.id,
        found_report_id=found_id,
        claimant_name="Aarav Sharma",
        contact_email="aarav@college.edu",
        claim_message="This is my laptop charger.",
        status="approved",
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)

    # 3. Generate Handover Code
    code_resp = client.post(
        f"/api/guest/cases/{case_ref}/handover/generate-code?key={secret_key}",
        json={
            "claim_id": claim.id,
            "agreed_location_type": "station_desk",
            "agreed_location_name": "Station Master Information Desk, Platform 1",
            "agreed_location_address": "Pune Central Station Concourse",
        },
    )
    assert code_resp.status_code == 200
    code_data = code_resp.json()
    handover_code = code_data["handover_code"]
    assert handover_code.startswith("HO-")
    assert code_data["status"] == "code_issued"

    # 4. Attempt confirmation with invalid code -> 400
    fail_confirm = client.post(
        f"/api/guest/cases/{case_ref}/handover/confirm?key={secret_key}",
        json={"handover_code": "HO-WRONG-CODE", "confirmed_by": "finder"},
    )
    assert fail_confirm.status_code == 400

    # 5. Confirm with valid code
    succ_confirm = client.post(
        f"/api/guest/cases/{case_ref}/handover/confirm?key={secret_key}",
        json={"handover_code": handover_code, "confirmed_by": "finder", "notes": "Handed over at station desk."},
    )
    assert succ_confirm.status_code == 200
    res_data = succ_confirm.json()
    assert res_data["success"] is True
    assert res_data["status"] == "completed"

    # 6. Verify underlying models updated
    db.expire_all()
    updated_report = db.get(ItemReport, found_id)
    assert updated_report.status == "returned"

    updated_claim = db.get(Claim, claim.id)
    assert updated_claim.status == "completed"

    hr = db.scalars(select(ClaimHandoverRecord).where(ClaimHandoverRecord.claim_id == claim.id)).first()
    assert hr is not None


# ---------------------------------------------------------------------------
# FEATURE 7: Rewards & Account Linking for Guest Finders
# ---------------------------------------------------------------------------

def test_guest_finder_account_linking_for_reward_eligibility(api):
    client, SessionLocal, _ = api
    db = SessionLocal()

    # 1. Guest creates found item report without account
    f_resp = client.post(
        "/api/guest/found",
        json={
            "item_name": "Sony Headphones",
            "category": "Electronics",
            "description": "Found in taxi back seat.",
            "location_text": "City Airport Terminal",
        },
    )
    receipt = f_resp.json()
    case_ref = receipt["case_reference"]
    secret_key = receipt["secret_key"]

    meta = db.scalars(
        select(GuestRecoveryReport).where(GuestRecoveryReport.case_reference == case_ref)
    ).first()
    assert meta.linked_account_email is None

    # 2. Finder later links verified account email
    link_resp = client.post(
        f"/api/guest/cases/{case_ref}/link-account?key={secret_key}",
        json={"email": "honest_driver@college.edu", "full_name": "Ramesh Kumar"},
    )
    assert link_resp.status_code == 200
    link_data = link_resp.json()
    assert link_data["success"] is True
    assert link_data["linked_account_email"] == "honest_driver@college.edu"

    db.expire_all()
    updated_meta = db.get(GuestRecoveryReport, meta.id)
    assert updated_meta.linked_account_email == "honest_driver@college.edu"
    assert updated_meta.linked_at is not None


# ---------------------------------------------------------------------------
# FEATURE 8: Transit QR Code Generation & Hub Destination
# ---------------------------------------------------------------------------

def test_transit_qr_config_and_svg_generation(api):
    client, _, _ = api

    resp = client.get("/api/guest/transit/qr-config?provider=PuneAutoUnion&hub=StationPlatform1")
    assert resp.status_code == 200
    data = resp.json()

    assert data["provider_id"] == "PuneAutoUnion"
    assert "/guest/found" in data["destination_url"]
    assert "hub=StationPlatform1" in data["destination_url"]
    assert "<svg" in data["qr_svg"]
    assert "<rect" in data["qr_svg"]
    assert "Park vehicle safely" in data["safety_notice"]


# ---------------------------------------------------------------------------
# FEATURE 9: Frontend Views Rendering
# ---------------------------------------------------------------------------

def test_guest_pages_render_cleanly(api):
    client, _, _ = api

    # 1. Guest found form
    r1 = client.get("/guest/found")
    assert r1.status_code == 200
    assert "I Found an Item" in r1.text
    assert "Driver Safety Warning" in r1.text
    assert "guest-found.js" in r1.text

    # 2. Guest lost form
    r2 = client.get("/guest/lost")
    assert r2.status_code == 200
    assert "I Lost an Item in Transit" in r2.text
    assert "guest-lost.js" in r2.text

    # 3. Guest case portal
    r3 = client.get("/guest/case/GF-TEST-CASE")
    assert r3.status_code == 200
    assert "GF-TEST-CASE" in r3.text
    assert "guest-case.js" in r3.text

    # 4. Transit QR generator
    r4 = client.get("/transit/qr")
    assert r4.status_code == 200
    assert "Configurable QR Access" in r4.text
    assert "transit-qr.js" in r4.text
