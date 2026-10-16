"""Automated tests for Travel Mode and Safe Handover Finder extension."""

import math
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import config
from app.db.database import Base, get_db
from app.extensions.safe_handover.providers import (
    BaseLocationProvider,
    OSMNominatimProvider,
    SimpleTTLCache,
)
from app.extensions.safe_handover.router import default_service
from app.extensions.safe_handover.schemas import (
    AcceptanceStatus,
    HandoverCategory,
    HandoverLocation,
    HandoverSearchRequest,
    RecommendationTier,
    TravelContext,
)
from app.extensions.safe_handover.service import (
    SafeHandoverService,
    classify_category,
    compute_location_score,
    evaluate_acceptance,
    generate_google_directions_url,
    generate_osm_directions_url,
    haversine_distance_km,
)
from app.main import app


# ---------------------------------------------------------------------------
# Test Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Isolated FastAPI test client fixture."""
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
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


class MockLocationProvider(BaseLocationProvider):
    """Controllable mock location provider for deterministic test runs."""

    def __init__(self, items=None, geocode_results=None, reverse_name=None):
        self.items = items or []
        self.geocode_results = geocode_results or []
        self.reverse_name = reverse_name or "Test Street, Test City"

    async def geocode(self, query: str, limit: int = 5):
        return self.geocode_results

    async def reverse_geocode(self, lat: float, lon: float):
        return self.reverse_name

    async def search_nearby(self, lat: float, lon: float, radius_km: float, category: str = "all", limit: int = 20):
        return self.items


# ---------------------------------------------------------------------------
# Requirement 13 & 14: Haversine Distance & Ranking Logic Unit Tests
# ---------------------------------------------------------------------------

def test_haversine_distance_known_coordinates():
    """Verify haversine straight-line distance against mathematically verified points."""
    # Zero distance for identical points
    assert haversine_distance_km(18.5204, 73.8567, 18.5204, 73.8567) == 0.0

    # Pune to Mumbai (~118 km direct)
    dist = haversine_distance_km(18.5204, 73.8567, 18.9388, 72.8354)
    assert 115.0 <= dist <= 125.0

    # London to Paris (~343 km direct)
    dist_london_paris = haversine_distance_km(51.5074, -0.1278, 48.8566, 2.3522)
    assert 340.0 <= dist_london_paris <= 348.0


def test_ranking_and_scoring_tiers():
    """Verify that primary tiers outscore secondary/conditional tiers at equal distances."""
    primary_score = compute_location_score(
        tier=RecommendationTier.PRIMARY,
        category=HandoverCategory.POLICE,
        travel_context=TravelContext.GENERAL,
        distance_km=1.0,
        has_phone=True,
        has_hours=True,
    )
    conditional_score = compute_location_score(
        tier=RecommendationTier.CONDITIONAL,
        category=HandoverCategory.POST_OFFICE,
        travel_context=TravelContext.GENERAL,
        distance_km=1.0,
        has_phone=True,
        has_hours=True,
    )
    assert primary_score > conditional_score

    # Context boost: train travel should boost transit category
    transit_general = compute_location_score(
        tier=RecommendationTier.SECONDARY,
        category=HandoverCategory.TRANSIT,
        travel_context=TravelContext.GENERAL,
        distance_km=1.0,
        has_phone=False,
        has_hours=False,
    )
    transit_boosted = compute_location_score(
        tier=RecommendationTier.SECONDARY,
        category=HandoverCategory.TRANSIT,
        travel_context=TravelContext.TRAIN_TRAVEL,
        distance_km=1.0,
        has_phone=False,
        has_hours=False,
    )
    assert transit_boosted > transit_general


# ---------------------------------------------------------------------------
# Requirement 15: External Directions Links
# ---------------------------------------------------------------------------

def test_external_directions_links_generation():
    """Ensure Google Maps and OSM directions links contain correct origin and destination coords."""
    g_url = generate_google_directions_url(18.5204, 73.8567, 18.5300, 73.8600)
    osm_url = generate_osm_directions_url(18.5204, 73.8567, 18.5300, 73.8600)

    assert "google.com/maps/dir" in g_url
    assert "origin=18.520400,73.856700" in g_url
    assert "destination=18.530000,73.860000" in g_url

    assert "openstreetmap.org/directions" in osm_url
    assert "route=18.520400,73.856700%3B18.530000,73.860000" in osm_url


# ---------------------------------------------------------------------------
# Requirement 9: Post Office & Facility Handover Caveats
# ---------------------------------------------------------------------------

def test_post_office_handover_caveats():
    """Verify that post offices require staff inquiry and display clear caveats."""
    status, note, tier, reason = evaluate_acceptance(HandoverCategory.POST_OFFICE, "Central Post Office")
    assert status == AcceptanceStatus.REQUIRES_STAFF_INQUIRY
    assert tier == RecommendationTier.CONDITIONAL
    assert "CAVEAT" in note
    assert "Ordinary post offices do NOT automatically accept" in note


def test_police_handover_status():
    """Verify police stations are marked as likely acceptance with primary tier."""
    status, note, tier, reason = evaluate_acceptance(HandoverCategory.POLICE, "City Police Station")
    assert status == AcceptanceStatus.LIKELY
    assert tier == RecommendationTier.PRIMARY
    assert "Official law enforcement facility" in note


# ---------------------------------------------------------------------------
# Requirement 1: Valid Coordinate-Based Searches (API)
# ---------------------------------------------------------------------------

def test_api_nearby_search_valid_coordinates(client, monkeypatch):
    """Test searching nearby handover points using valid GPS coordinates."""
    mock_items = [
        {
            "place_id": 101,
            "osm_id": 201,
            "name": "Central Police Station",
            "lat": "18.5220",
            "lon": "73.8580",
            "category": "amenity",
            "type": "police",
            "display_name": "Central Police Station, Station Road, Pune",
            "address": {"road": "Station Road", "city": "Pune"},
            "extratags": {"phone": "+91 20 1234 5678", "opening_hours": "24/7"},
        }
    ]
    mock_provider = MockLocationProvider(items=mock_items)
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    payload = {
        "latitude": 18.5204,
        "longitude": 73.8567,
        "radius_km": 5.0,
        "category": "all",
        "travel_context": "general",
    }
    resp = client.post("/api/handover/nearby", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["query_latitude"] == 18.5204
    assert data["query_longitude"] == 73.8567
    assert data["search_radius_km"] == 5.0
    assert "safety_disclaimer" in data
    assert len(data["locations"]) >= 1

    police_loc = next((loc for loc in data["locations"] if loc["name"] == "Central Police Station"), None)
    assert police_loc is not None
    assert police_loc["category"] == "police"
    assert "straight-line" in police_loc["distance_label"]
    assert police_loc["phone"] == "+91 20 1234 5678"
    assert police_loc["operating_hours"] == "24/7"
    assert "google.com/maps/dir" in police_loc["directions_url_google"]


def test_api_nearby_search_get_endpoint(client, monkeypatch):
    """Test GET /api/handover/nearby query parameters."""
    mock_items = [
        {
            "place_id": 102,
            "name": "Civic Assistance Desk",
            "lat": "18.5210",
            "lon": "73.8570",
            "category": "amenity",
            "type": "townhall",
            "display_name": "Civic Assistance Desk, Pune",
        }
    ]
    mock_provider = MockLocationProvider(items=mock_items)
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    resp = client.get("/api/handover/nearby?lat=18.5204&lon=73.8567&radius_km=3.0&category=all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["search_radius_km"] == 3.0
    assert data["total_found"] >= 1


# ---------------------------------------------------------------------------
# Requirement 2: Manual Location-Based Searches (Geocoding)
# ---------------------------------------------------------------------------

def test_api_geocode_search(client, monkeypatch):
    """Test resolving a place or landmark query to coordinates."""
    from app.extensions.safe_handover.schemas import GeocodeResult

    mock_results = [
        GeocodeResult(
            display_name="Pune Railway Station, Agarkar Nagar, Pune",
            latitude=18.5284,
            longitude=73.8744,
            place_type="station",
            importance=0.85,
        )
    ]
    mock_provider = MockLocationProvider(geocode_results=mock_results)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_provider", mock_provider)

    resp = client.get("/api/handover/geocode?q=Pune+Railway+Station")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Pune Railway Station"
    assert len(data["results"]) == 1
    assert data["results"][0]["latitude"] == 18.5284
    assert data["results"][0]["longitude"] == 73.8744


# ---------------------------------------------------------------------------
# Requirement 3: Invalid Coordinates Validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "lat,lon,radius_km",
    [
        (95.0, 73.8567, 5.0),    # Latitude > 90
        (-95.0, 73.8567, 5.0),   # Latitude < -90
        (18.52, 190.0, 5.0),     # Longitude > 180
        (18.52, -190.0, 5.0),    # Longitude < -180
        (18.52, 73.8567, -2.0),  # Negative radius
        (18.52, 73.8567, 0.0),   # Zero radius
        (18.52, 73.8567, 60.0),  # Radius exceeds 50km
    ],
)
def test_invalid_coordinates_rejected(client, lat, lon, radius_km):
    """Ensure invalid coordinates or radius trigger 422 Unprocessable Entity."""
    # Test POST endpoint
    resp = client.post(
        "/api/handover/nearby",
        json={"latitude": lat, "longitude": lon, "radius_km": radius_km},
    )
    assert resp.status_code == 422

    # Test GET endpoint
    resp_get = client.get(
        f"/api/handover/nearby?lat={lat}&lon={lon}&radius_km={radius_km}"
    )
    assert resp_get.status_code == 422


# ---------------------------------------------------------------------------
# Requirement 5: No Nearby Facilities
# ---------------------------------------------------------------------------

def test_no_nearby_facilities(client, monkeypatch):
    """When no facilities exist in the radius, return empty list gracefully."""
    # Point located far away from configured campus (e.g. middle of the Indian Ocean)
    mock_provider = MockLocationProvider(items=[])
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    payload = {
        "latitude": -10.0,
        "longitude": 75.0,
        "radius_km": 2.0,
        "category": "police",
    }
    resp = client.post("/api/handover/nearby", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_found"] == 0
    assert data["locations"] == []


# ---------------------------------------------------------------------------
# Requirement 6: Multiple Facility Categories
# ---------------------------------------------------------------------------

def test_category_filtering(client, monkeypatch):
    """Ensure category filtering properly restricts returned location types."""
    mock_items = [
        {
            "place_id": 1,
            "name": "District Police HQ",
            "lat": "18.521",
            "lon": "73.857",
            "category": "amenity",
            "type": "police",
            "display_name": "District Police HQ",
        },
        {
            "place_id": 2,
            "name": "General Post Office",
            "lat": "18.523",
            "lon": "73.859",
            "category": "amenity",
            "type": "post_office",
            "display_name": "General Post Office",
        },
    ]
    mock_provider = MockLocationProvider(items=mock_items)
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    # Filter for police only
    resp_police = client.post(
        "/api/handover/nearby",
        json={"latitude": 18.5204, "longitude": 73.8567, "category": "police"},
    )
    data_police = resp_police.json()
    assert all(loc["category"] == "police" for loc in data_police["locations"])

    # Filter for post office only
    resp_post = client.post(
        "/api/handover/nearby",
        json={"latitude": 18.5204, "longitude": 73.8567, "category": "post_office"},
    )
    data_post = resp_post.json()
    assert all(loc["category"] == "post_office" for loc in data_post["locations"])


# ---------------------------------------------------------------------------
# Requirement 7: Duplicate Provider Results Handling
# ---------------------------------------------------------------------------

def test_duplicate_provider_results_deduplication(client, monkeypatch):
    """Ensure duplicate locations within 50m or with identical names are merged."""
    mock_items = [
        {
            "place_id": 101,
            "osm_id": 5001,
            "name": "Pune City Police Chowki",
            "lat": "18.5220",
            "lon": "73.8580",
            "category": "amenity",
            "type": "police",
            "display_name": "Pune City Police Chowki, Main Road",
            "extratags": {},
        },
        {
            "place_id": 102,
            "osm_id": 5002,
            "name": "Pune City Police Chowki",  # Exact duplicate entry in OSM
            "lat": "18.5221",  # ~11 meters apart
            "lon": "73.8581",
            "category": "amenity",
            "type": "police",
            "display_name": "Pune City Police Chowki, Main Road",
            "extratags": {"phone": "+91 20 9999 8888"},  # Has phone info
        },
    ]
    mock_provider = MockLocationProvider(items=mock_items)
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    resp = client.post(
        "/api/handover/nearby",
        json={"latitude": 18.5204, "longitude": 73.8567, "category": "police"},
    )
    data = resp.json()

    # Should be deduplicated into a single entry
    police_entries = [loc for loc in data["locations"] if "Pune City Police" in loc["name"]]
    assert len(police_entries) == 1
    # Metadata should have merged phone number
    assert police_entries[0]["phone"] == "+91 20 9999 8888"


# ---------------------------------------------------------------------------
# Requirement 8: Missing Phone and Operating Hours (No Fabrication)
# ---------------------------------------------------------------------------

def test_missing_phone_and_hours_not_fabricated(client, monkeypatch):
    """Verify that unlisted phone and operating hours remain None."""
    mock_items = [
        {
            "place_id": 105,
            "name": "Local Help Desk",
            "lat": "18.5220",
            "lon": "73.8580",
            "category": "amenity",
            "type": "police",
            "display_name": "Local Help Desk",
            "extratags": {},  # No phone, no opening_hours
        }
    ]
    mock_provider = MockLocationProvider(items=mock_items)
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    resp = client.post(
        "/api/handover/nearby",
        json={"latitude": 18.5204, "longitude": 73.8567, "category": "police"},
    )
    data = resp.json()
    desk = next(loc for loc in data["locations"] if loc["name"] == "Local Help Desk")
    assert desk["phone"] is None
    assert desk["operating_hours"] is None


# ---------------------------------------------------------------------------
# Requirements 10, 11, 12: Provider Timeout, Error, and Malformed Responses
# ---------------------------------------------------------------------------

def test_osm_provider_timeout_graceful():
    """Verify provider handles HTTP timeouts without raising uncaught exceptions."""
    import asyncio

    async def _run():
        provider = OSMNominatimProvider(timeout=0.001)
        with patch("httpx.AsyncClient.get", side_effect=httpx.TimeoutException("Timeout connecting")):
            results = await provider.search_nearby(18.5204, 73.8567, 5.0)
            assert results == []

            geo = await provider.geocode("Test City")
            assert geo == []

            rgeo = await provider.reverse_geocode(18.5204, 73.8567)
            assert rgeo is None

    asyncio.run(_run())


def test_osm_provider_http_error_graceful():
    """Verify provider handles HTTP 500/503 errors gracefully."""
    import asyncio

    async def _run():
        provider = OSMNominatimProvider()
        mock_response = httpx.Response(status_code=503, content=b"Service Unavailable")
        with patch("httpx.AsyncClient.get", return_value=mock_response):
            results = await provider.search_nearby(18.5204, 73.8567, 5.0)
            assert results == []

    asyncio.run(_run())


def test_malformed_provider_records_skipped(client, monkeypatch):
    """Ensure malformed or incomplete records from provider are skipped safely."""
    mock_items = [
        {"invalid": "no coordinates"},
        {"lat": "not_a_number", "lon": "73.85"},
        {"lat": "18.52", "lon": "not_a_number"},
        {
            "place_id": 200,
            "name": "Valid Facility",
            "lat": "18.521",
            "lon": "73.857",
            "type": "police",
        },
    ]
    mock_provider = MockLocationProvider(items=mock_items)
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    resp = client.post(
        "/api/handover/nearby",
        json={"latitude": 18.5204, "longitude": 73.8567, "category": "police"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Malformed ones skipped, valid one kept
    names = [loc["name"] for loc in data["locations"]]
    assert "Valid Facility" in names


# ---------------------------------------------------------------------------
# Requirement 16: Search Without a Previously Created Report
# ---------------------------------------------------------------------------

def test_independent_search_without_prior_report(client, monkeypatch):
    """Ensure search works as a standalone tool without report creation or auth cookies."""
    mock_provider = MockLocationProvider(items=[])
    custom_service = SafeHandoverService(provider=mock_provider)
    monkeypatch.setattr("app.extensions.safe_handover.router.default_service", custom_service)

    # Empty cookie/session request
    resp = client.get("/api/handover/nearby?lat=18.5204&lon=73.8567&radius_km=5.0")
    assert resp.status_code == 200
    data = resp.json()
    assert "locations" in data
    assert "safety_disclaimer" in data


# ---------------------------------------------------------------------------
# Requirement 17: Integration with UI and Found Report Flow
# ---------------------------------------------------------------------------

def test_travel_handover_frontend_page_renders(client):
    """Verify /travel-handover page renders 200 OK with map and search elements."""
    resp = client.get("/travel-handover")
    assert resp.status_code == 200
    html = resp.text
    assert "Nearby Safe Handover Locations" in html
    assert "Use my current location" in html
    assert "leaflet.js" in html.lower()
    assert "handover-map" in html
    assert "Safety First" in html


def test_base_navigation_includes_safe_handover(client):
    """Verify top navigation includes the Travel & Handover link."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "/travel-handover" in resp.text


def test_home_page_includes_safe_handover_action(client):
    """Verify home page hero includes Safe Handover button."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Safe handover 📍" in resp.text


def test_report_found_page_includes_handover_guidance(client):
    """Verify report found item page references the handover finder."""
    resp = client.get("/report/found")
    assert resp.status_code == 200
    assert "/travel-handover" in resp.text


# ---------------------------------------------------------------------------
# Requirement 18: Category Metadata & Campus Endpoints
# ---------------------------------------------------------------------------

def test_categories_endpoint(client):
    """Verify /api/handover/categories returns all recognized categories."""
    resp = client.get("/api/handover/categories")
    assert resp.status_code == 200
    categories = resp.json()
    cat_ids = [c["id"] for c in categories]
    assert "police" in cat_ids
    assert "campus_security" in cat_ids
    assert "transit" in cat_ids
    assert "post_office" in cat_ids


def test_campus_handover_endpoint(client):
    """Verify /api/handover/campus returns the configured primary campus security desk."""
    resp = client.get("/api/handover/campus")
    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "campus_security"
    assert data["latitude"] == config.CAMPUS_LATITUDE
    assert data["longitude"] == config.CAMPUS_LONGITUDE
    assert data["operating_hours"] == config.CAMPUS_HOURS
