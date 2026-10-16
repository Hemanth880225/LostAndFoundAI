from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ItemReport
from app.schemas.reports import ItemReportCreate
from app.services.report_service import (
    create_report,
    get_report,
    list_reports,
)


@pytest.fixture
def db():
    """Create an isolated in-memory SQLite database for each test."""

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


def make_payload(
    report_type="lost",
    item_name="Black wallet",
):
    return ItemReportCreate(
        report_type=report_type,
        item_name=item_name,
        category="accessories",
        color="black",
        brand=None,
        model=None,
        description="Black leather wallet with several cards",
        event_date=date(2026, 10, 10),
        location_text="College library",
    )


def test_create_report_saves_active_report(db):
    payload = make_payload()

    report = create_report(db, payload)

    assert report.id is not None
    assert report.report_type == "lost"
    assert report.item_name == "Black wallet"
    assert report.status == "active"


def test_get_report_returns_existing_report(db):
    created = create_report(db, make_payload())

    retrieved = get_report(db, created.id)

    assert retrieved is not None
    assert retrieved.id == created.id
    assert retrieved.item_name == "Black wallet"


def test_get_report_returns_none_for_missing_id(db):
    assert get_report(db, 99999) is None


def test_list_reports_returns_all_report_types(db):
    create_report(db, make_payload("lost", "Black wallet"))
    create_report(db, make_payload("found", "Blue bag"))

    reports = list_reports(db)

    assert len(reports) == 2
    assert {report.report_type for report in reports} == {
        "lost",
        "found",
    }


def test_list_reports_filters_by_type(db):
    create_report(db, make_payload("lost", "Black wallet"))
    create_report(db, make_payload("found", "Blue bag"))
    create_report(db, make_payload("lost", "Silver keys"))

    reports = list_reports(db, report_type="lost")

    assert len(reports) == 2
    assert all(report.report_type == "lost" for report in reports)


def test_list_reports_respects_limit(db):
    create_report(db, make_payload("lost", "Black wallet"))
    create_report(db, make_payload("found", "Blue bag"))
    create_report(db, make_payload("lost", "Silver keys"))

    reports = list_reports(db, limit=2)

    assert len(reports) == 2


def test_list_reports_rejects_invalid_report_type(db):
    with pytest.raises(ValueError):
        list_reports(db, report_type="unknown")


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_list_reports_rejects_invalid_limits(db, limit):
    with pytest.raises(ValueError):
        list_reports(db, limit=limit)
