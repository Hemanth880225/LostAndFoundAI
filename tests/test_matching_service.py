from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ItemReport
from app.services.matching_service import find_matches


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


def make_report(
    db,
    report_type,
    item_name,
    category="electronics",
    color="black",
):
    report = ItemReport(
        report_type=report_type,
        item_name=item_name,
        category=category,
        color=color,
        description=f"{color} {item_name}",
        event_date=date(2026, 10, 10),
        location_text="College library",
        latitude=18.5204,
        longitude=73.8567,
        status="active",
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def fake_score_candidate(db, lost, found):
    """Return deterministic scores without loading CLIP."""

    score = 90.0 if lost.category == found.category else 30.0

    return {
        "score": score,
        "components": {
            "text": 0.9 if score == 90.0 else 0.3,
            "attributes": 1.0 if score == 90.0 else 0.0,
            "location": 1.0,
            "time": 1.0,
        },
    }


def fake_evaluate_match(lost, found, components):
    """Provide predictable rule-engine output."""

    plausible = lost.category == found.category

    return {
        "plausible_match": plausible,
        "forward_chaining_facts": [],
        "backward_chaining_goal_proven": plausible,
        "backtracking_evidence": (
            ["category_match", "text_similar"]
            if plausible
            else None
        ),
    }


def test_find_matches_returns_opposite_type_candidates(db):
    lost = make_report(db, "lost", "Black phone")
    make_report(db, "found", "Black phone")
    make_report(db, "lost", "Another phone")

    with (
        patch(
            "app.services.matching_service.score_candidate",
            side_effect=fake_score_candidate,
        ),
        patch(
            "app.services.matching_service.evaluate_match",
            side_effect=fake_evaluate_match,
        ),
    ):
        result = find_matches(db, lost.id)

    assert result["source_report_id"] == lost.id
    assert result["candidate_count"] == 1
    assert result["matches"][0]["report_type"] == "found"


def test_find_matches_ranks_plausible_candidates_first(db):
    lost = make_report(db, "lost", "Black phone")

    make_report(
        db, "found", "Different item",
        category="clothing", color="blue",
    )
    make_report(db, "found", "Similar phone")

    with (
        patch(
            "app.services.matching_service.score_candidate",
            side_effect=fake_score_candidate,
        ),
        patch(
            "app.services.matching_service.evaluate_match",
            side_effect=fake_evaluate_match,
        ),
    ):
        result = find_matches(db, lost.id)

    assert result["matches"][0]["reasoning"]["plausible_match"] is True
    assert result["matches"][0]["match_score"] == 90.0


def test_find_matches_respects_limit(db):
    lost = make_report(db, "lost", "Black phone")
    make_report(db, "found", "Phone one")
    make_report(db, "found", "Phone two")
    make_report(db, "found", "Phone three")

    with (
        patch(
            "app.services.matching_service.score_candidate",
            side_effect=fake_score_candidate,
        ),
        patch(
            "app.services.matching_service.evaluate_match",
            side_effect=fake_evaluate_match,
        ),
    ):
        result = find_matches(db, lost.id, limit=2)

    assert result["candidate_count"] == 3
    assert len(result["matches"]) == 2


def test_find_matches_rejects_missing_report(db):
    with pytest.raises(ValueError, match="Report not found"):
        find_matches(db, 99999)


def test_find_matches_rejects_inactive_report(db):
    report = make_report(db, "lost", "Black phone")
    report.status = "returned"
    db.commit()

    with pytest.raises(ValueError, match="Only active reports"):
        find_matches(db, report.id)


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_find_matches_rejects_invalid_limit(db, limit):
    with pytest.raises(ValueError, match="Limit must be between"):
        find_matches(db, 1, limit=limit)
