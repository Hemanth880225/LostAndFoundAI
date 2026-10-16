"""Comprehensive frontend routes and integration tests for LostAndFoundAI."""

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
def test_db():
    """Isolated in-memory SQLite database for frontend integration testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def client(test_db):
    """FastAPI TestClient with overridden database dependency."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_home_page_renders_with_ai_search(client):
    """Verify home page loads successfully and contains the integrated AI search panel."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Lost something?" in resp.text
    assert "home-search-container" in resp.text
    assert "Search Using a Photo" in resp.text
    assert "Report a Lost Item" in resp.text
    assert "Report a Found Item" in resp.text


def test_browse_page_renders_with_filters(client):
    """Verify browse directory loads with filter controls and quick actions."""
    resp = client.get("/browse")
    assert resp.status_code == 200
    assert "Help something" in resp.text
    assert "type-filter" in resp.text
    assert "category-filter" in resp.text
    assert "campus-filter" in resp.text


def test_photo_search_page_renders(client):
    """Verify dedicated photo search page renders dropzone and multi-modal controls."""
    resp = client.get("/search/image")
    assert resp.status_code == 200
    assert "Search with a photo" in resp.text
    assert "query-upload-box" in resp.text
    assert "attribute-filter-accordion" in resp.text


def test_report_form_lost_and_found_render(client):
    """Verify report form renders structured sections A, B, C, D for both lost and found."""
    resp_lost = client.get("/report/lost")
    assert resp_lost.status_code == 200
    assert "Tell us what you’ve lost." in resp_lost.text
    assert "Item Information" in resp_lost.text
    assert "upload-box" in resp_lost.text
    assert "campus-location-select" in resp_lost.text
    assert "btn-use-gps" in resp_lost.text

    resp_found = client.get("/report/found")
    assert resp_found.status_code == 200
    assert "Tell us what you’ve found." in resp_found.text


def test_report_detail_and_matches_render(client, test_db):
    """Verify detail page and matches page render for an existing active report."""
    rep = ItemReport(
        report_type="lost",
        item_name="Navy Blue Laptop Bag",
        category="Backpack",
        color="Navy Blue",
        description="Padded laptop backpack with red zipper tag left in library.",
        event_date=date.today(),
        location_text="Central Library 2nd Floor",
        status="active",
    )
    test_db.add(rep)
    test_db.commit()
    test_db.refresh(rep)

    resp_detail = client.get(f"/reports/{rep.id}")
    assert resp_detail.status_code == 200
    assert f'data-id="{rep.id}"' in resp_detail.text

    resp_matches = client.get(f"/reports/{rep.id}/matches")
    assert resp_matches.status_code == 200
    assert f'data-id="{rep.id}"' in resp_matches.text
    assert "Potential matches" in resp_matches.text


def test_my_reports_and_my_claims_tracking_portals(client):
    """Verify /my-reports and /my-claims render functional tracking portals."""
    resp_rep = client.get("/my-reports")
    assert resp_rep.status_code == 200
    assert "Track reports and cases" in resp_rep.text
    assert "lookup-report-form" in resp_rep.text
    assert "Saved on this device" in resp_rep.text

    resp_claim = client.get("/my-claims")
    assert resp_claim.status_code == 200
    assert "Track your claim status" in resp_claim.text
    assert "lookup-claim-form" in resp_claim.text


def test_travel_handover_page_renders(client):
    """Verify travel handover finder renders interactive map wrapper and filters."""
    resp = client.get("/travel-handover")
    assert resp.status_code == 200
    assert "Nearby Safe Handover Locations" in resp.text
    assert "btn-use-gps" in resp.text
    assert "handover-map" in resp.text


def test_rewards_page_renders(client):
    """Verify rewards page renders calculator and ledger lookup."""
    resp = client.get("/rewards")
    assert resp.status_code == 200
    assert "Value-Based Reward Points" in resp.text
    assert "calc-form" in resp.text


def test_guest_found_and_lost_pages_render(client):
    """Verify guest transit reporting pages render with safety warnings."""
    resp_found = client.get("/guest/found")
    assert resp_found.status_code == 200
    assert "I Found an Item" in resp_found.text
    assert "Driver Safety Warning" in resp_found.text

    resp_lost = client.get("/guest/lost")
    assert resp_lost.status_code == 200
    assert "I Lost an Item" in resp_lost.text


def test_claim_status_page_renders(client, test_db):
    """Verify claim status portal renders for a valid claim."""
    lost_rep = ItemReport(
        report_type="lost",
        item_name="Lost Watch",
        category="Watch",
        description="Silver analog watch",
        event_date=date.today(),
        location_text="Gym",
        status="active",
    )
    found_rep = ItemReport(
        report_type="found",
        item_name="Found Watch",
        category="Watch",
        description="Silver analog watch found near bench",
        event_date=date.today(),
        location_text="Gym",
        status="active",
    )
    test_db.add_all([lost_rep, found_rep])
    test_db.commit()

    claim = Claim(
        lost_report_id=lost_rep.id,
        found_report_id=found_rep.id,
        claimant_name="Aarav Mehta",
        contact_email="aarav@college.edu",
        claim_message="This is my watch lost after workout.",
        status="submitted",
    )
    test_db.add(claim)
    test_db.commit()
    test_db.refresh(claim)

    resp = client.get(f"/claims/{claim.id}")
    assert resp.status_code == 200
    assert f"Claim #{claim.id} Status" in resp.text


def test_help_page_renders_comprehensive_guide(client):
    """Verify help page renders safety guidelines and multimodal matching explanation."""
    resp = client.get("/help")
    assert resp.status_code == 200
    assert "Good to know" in resp.text
    assert "Multimodal AI Similarity" in resp.text
    assert "Safe Handover Points" in resp.text
    assert "Honest Finder Rewards" in resp.text


def test_static_assets_delivery(client):
    """Verify CSS and JavaScript static assets are accessible."""
    resp_css = client.get("/static/css/app.css")
    assert resp_css.status_code == 200
    assert "FOUNDLY MODERN FRONTEND INTEGRATION" in resp_css.text

    resp_js = client.get("/static/js/app.js")
    assert resp_js.status_code == 200
    assert "window.Foundly" in resp_js.text
