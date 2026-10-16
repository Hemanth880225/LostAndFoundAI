from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.main import app


@pytest.fixture
def client():
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
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def report_payload(**overrides):
    payload = {
        "report_type": "lost",
        "item_name": "Black smartphone",
        "category": "electronics",
        "color": "black",
        "brand": "Samsung",
        "model": "Galaxy S",
        "description": "Black smartphone lost near the college library.",
        "event_date": date(2026, 10, 10).isoformat(),
        "location_text": "College library",
        "latitude": 18.5204,
        "longitude": 73.8567,
    }
    payload.update(overrides)
    return payload


def test_health_endpoint(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert response.json()["service"] == "ai-lost-and-found"


def test_create_report_returns_201(client):
    response = client.post(
        "/api/reports",
        json=report_payload(),
    )

    assert response.status_code == 201

    data = response.json()
    assert data["id"] > 0
    assert data["report_type"] == "lost"
    assert data["item_name"] == "Black smartphone"
    assert data["status"] == "active"


def test_create_report_trims_required_text(client):
    response = client.post(
        "/api/reports",
        json=report_payload(
            item_name="  Black smartphone  ",
            category="  electronics  ",
            location_text="  College library  ",
        ),
    )

    assert response.status_code == 201

    data = response.json()
    assert data["item_name"] == "Black smartphone"
    assert data["category"] == "electronics"
    assert data["location_text"] == "College library"


def test_create_report_rejects_blank_required_text(client):
    response = client.post(
        "/api/reports",
        json=report_payload(item_name="   "),
    )

    assert response.status_code == 422


def test_create_report_rejects_invalid_report_type(client):
    response = client.post(
        "/api/reports",
        json=report_payload(report_type="missing"),
    )

    assert response.status_code == 422


def test_create_report_requires_both_coordinates(client):
    response = client.post(
        "/api/reports",
        json=report_payload(longitude=None),
    )

    assert response.status_code == 422


def test_create_report_rejects_out_of_range_coordinates(client):
    response = client.post(
        "/api/reports",
        json=report_payload(latitude=100),
    )

    assert response.status_code == 422


def test_list_reports_returns_created_reports(client):
    client.post("/api/reports", json=report_payload())
    client.post(
        "/api/reports",
        json=report_payload(
            report_type="found",
            item_name="Blue backpack",
            category="bags",
            color="blue",
            description="Blue backpack found in the college cafeteria.",
        ),
    )

    response = client.get("/api/reports")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_reports_filters_by_type(client):
    client.post("/api/reports", json=report_payload())
    client.post(
        "/api/reports",
        json=report_payload(
            report_type="found",
            item_name="Blue backpack",
            category="bags",
            color="blue",
            description="Blue backpack found in the college cafeteria.",
        ),
    )

    response = client.get(
        "/api/reports",
        params={"report_type": "found"},
    )

    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["report_type"] == "found"


def test_list_reports_rejects_invalid_type(client):
    response = client.get(
        "/api/reports",
        params={"report_type": "missing"},
    )

    assert response.status_code == 400


def test_list_reports_rejects_invalid_limit(client):
    response = client.get(
        "/api/reports",
        params={"limit": 0},
    )

    assert response.status_code == 422


def test_get_report_returns_existing_report(client):
    created = client.post(
        "/api/reports",
        json=report_payload(),
    )
    report_id = created.json()["id"]

    response = client.get(f"/api/reports/{report_id}")

    assert response.status_code == 200
    assert response.json()["id"] == report_id
    assert response.json()["item_name"] == "Black smartphone"


def test_get_report_returns_404_for_missing_report(client):
    response = client.get("/api/reports/99999")

    assert response.status_code == 404
    assert response.json()["detail"] == "Report not found."
