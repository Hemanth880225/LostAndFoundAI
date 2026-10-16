from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai import rule_engine
from app.db.database import Base, get_db
from app.db.models import ItemReport
from app.main import app
from app.services import matching_service


@pytest.fixture
def api(monkeypatch):
    """Provide a test client backed by isolated in-memory SQLite."""

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

    # Do not enter the TestClient context manager: the app lifespan
    # could initialize the real application database.
    client = TestClient(app)

    yield client, TestingSessionLocal

    client.close()
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def make_report(
    db,
    report_type="lost",
    item_name="Black smartphone",
    status="active",
):
    report = ItemReport(
        report_type=report_type,
        item_name=item_name,
        category="electronics",
        color="black",
        brand="Samsung",
        model="Galaxy S",
        description=f"{item_name} reported near the college library.",
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


def mock_scoring(monkeypatch, scores=None):
    """Replace expensive AI scoring with deterministic test scores."""

    scores = scores or {}

    def fake_score_candidate(db, lost, found):
        score = scores.get(found.id, 80.0)
        return {
            "score": score,
            "components": {
                "text": score / 100,
                "attributes": 0.8,
            },
        }

    monkeypatch.setattr(
        matching_service,
        "score_candidate",
        fake_score_candidate,
    )

    monkeypatch.setattr(
        matching_service,
        "evaluate_match",
        lambda lost, found, components: {
            "plausible_match": True,
            "evidence": ["test evidence"],
            "explanation": "Deterministic test result.",
        },
    )


def test_matches_returns_expected_response_structure(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        found = make_report(
            db,
            "found",
            item_name="Black Samsung phone",
        )
        lost_id = lost.id
        found_id = found.id

    mock_scoring(monkeypatch)

    response = client.get(f"/api/reports/{lost_id}/matches")

    assert response.status_code == 200, response.text

    data = response.json()
    assert data["source_report_id"] == lost_id
    assert data["candidate_count"] == 1
    assert len(data["matches"]) == 1

    match = data["matches"][0]
    assert match["report_id"] == found_id
    assert match["item_name"] == "Black Samsung phone"
    assert match["report_type"] == "found"
    assert match["match_score"] == 80.0
    assert "score_components" in match
    assert "reasoning" in match


def test_matches_returns_empty_list_when_no_candidates(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        lost_id = lost.id

    mock_scoring(monkeypatch)

    response = client.get(f"/api/reports/{lost_id}/matches")

    assert response.status_code == 200
    assert response.json() == {
        "source_report_id": lost_id,
        "candidate_count": 0,
        "matches": [],
    }


def test_matches_returns_404_for_missing_report(api):
    client, _ = api

    response = client.get("/api/reports/99999/matches")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_matches_rejects_inactive_source_report(api):
    client, session_factory = api

    with session_factory() as db:
        report = make_report(db, "lost", status="returned")
        report_id = report.id

    response = client.get(f"/api/reports/{report_id}/matches")

    assert response.status_code == 400
    assert "active" in response.json()["detail"].lower()


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_matches_rejects_invalid_limit(api, limit):
    client, session_factory = api

    with session_factory() as db:
        report = make_report(db, "lost")
        report_id = report.id

    response = client.get(
        f"/api/reports/{report_id}/matches",
        params={"limit": limit},
    )

    assert response.status_code == 422


def test_matches_rejects_non_integer_limit(api):
    client, session_factory = api

    with session_factory() as db:
        report = make_report(db, "lost")
        report_id = report.id

    response = client.get(
        f"/api/reports/{report_id}/matches",
        params={"limit": "abc"},
    )

    assert response.status_code == 422


def test_matches_excludes_same_type_reports(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        another_lost = make_report(
            db,
            "lost",
            item_name="Another lost phone",
        )
        found = make_report(
            db,
            "found",
            item_name="Found phone",
        )

        lost_id = lost.id
        another_lost_id = another_lost.id
        found_id = found.id

    mock_scoring(monkeypatch)

    response = client.get(f"/api/reports/{lost_id}/matches")

    assert response.status_code == 200
    data = response.json()

    returned_ids = [item["report_id"] for item in data["matches"]]
    assert returned_ids == [found_id]
    assert another_lost_id not in returned_ids


def test_matches_excludes_inactive_candidates(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        active_found = make_report(
            db,
            "found",
            item_name="Active found phone",
        )
        inactive_found = make_report(
            db,
            "found",
            item_name="Returned phone",
            status="returned",
        )

        lost_id = lost.id
        active_id = active_found.id
        inactive_id = inactive_found.id

    mock_scoring(monkeypatch)

    response = client.get(f"/api/reports/{lost_id}/matches")

    assert response.status_code == 200
    returned_ids = [
        item["report_id"] for item in response.json()["matches"]
    ]

    assert active_id in returned_ids
    assert inactive_id not in returned_ids


def test_matches_respects_limit(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        found_reports = [
            make_report(
                db,
                "found",
                item_name=f"Found phone {index}",
            )
            for index in range(3)
        ]
        lost_id = lost.id

    mock_scoring(monkeypatch)

    response = client.get(
        f"/api/reports/{lost_id}/matches",
        params={"limit": 2},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["candidate_count"] == 3
    assert len(data["matches"]) == 2


def test_matches_ranks_higher_scores_first(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        lower = make_report(
            db,
            "found",
            item_name="Lower-scoring phone",
        )
        higher = make_report(
            db,
            "found",
            item_name="Higher-scoring phone",
        )

        lost_id = lost.id
        lower_id = lower.id
        higher_id = higher.id

    mock_scoring(
        monkeypatch,
        scores={
            lower_id: 40.0,
            higher_id: 95.0,
        },
    )

    response = client.get(f"/api/reports/{lost_id}/matches")

    assert response.status_code == 200
    matches = response.json()["matches"]

    assert matches[0]["report_id"] == higher_id
    assert matches[1]["report_id"] == lower_id


def test_rule_supported_match_ranks_before_higher_score(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        lost = make_report(db, "lost")
        higher_score = make_report(
            db,
            "found",
            item_name="Higher score but unsupported",
        )
        rule_supported = make_report(
            db,
            "found",
            item_name="Rule-supported candidate",
        )

        lost_id = lost.id
        higher_id = higher_score.id
        supported_id = rule_supported.id

    mock_scoring(
        monkeypatch,
        scores={
            higher_id: 99.0,
            supported_id: 60.0,
        },
    )

    def fake_evaluate(lost, found, components):
        return {
            "plausible_match": found.id == supported_id,
            "evidence": [],
            "explanation": "Deterministic ranking test.",
        }

    monkeypatch.setattr(
        matching_service,
        "evaluate_match",
        fake_evaluate,
    )

    response = client.get(f"/api/reports/{lost_id}/matches")

    assert response.status_code == 200
    matches = response.json()["matches"]

    assert matches[0]["report_id"] == supported_id
    assert matches[1]["report_id"] == higher_id


def test_found_source_can_match_lost_candidates(api, monkeypatch):
    client, session_factory = api

    with session_factory() as db:
        found = make_report(db, "found")
        lost = make_report(
            db,
            "lost",
            item_name="Reported lost smartphone",
        )

        found_id = found.id
        lost_id = lost.id

    mock_scoring(monkeypatch)

    response = client.get(f"/api/reports/{found_id}/matches")

    assert response.status_code == 200
    matches = response.json()["matches"]

    assert len(matches) == 1
    assert matches[0]["report_id"] == lost_id
    assert matches[0]["report_type"] == "lost"
