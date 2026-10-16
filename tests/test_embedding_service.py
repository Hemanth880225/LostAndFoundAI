from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import ItemEmbedding, ItemReport
from app.services.embedding_service import (
    get_embedding,
    save_embedding,
)


@pytest.fixture
def db():
    """Create an isolated in-memory database for each test."""

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


def make_report(db):
    """Create a report to which embeddings can belong."""

    report = ItemReport(
        report_type="lost",
        item_name="Black wallet",
        category="accessories",
        description="Black leather wallet with cards",
        event_date=date(2026, 10, 10),
        location_text="College library",
    )

    db.add(report)
    db.commit()
    db.refresh(report)

    return report


def test_get_embedding_returns_none_when_missing(db):
    report = make_report(db)

    result = get_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        model_name="test-model",
    )

    assert result is None


def test_save_embedding_creates_new_embedding(db):
    report = make_report(db)
    vector = [0.1, 0.2, 0.3]

    saved = save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=vector,
        model_name="test-model",
    )

    assert saved.id is not None
    assert saved.report_id == report.id
    assert saved.embedding_type == "text"
    assert saved.vector == vector


def test_get_embedding_retrieves_saved_vector(db):
    report = make_report(db)
    vector = [0.25, 0.50, 0.75]

    save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=vector,
        model_name="test-model",
    )

    result = get_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        model_name="test-model",
    )

    assert result == vector


def test_save_embedding_updates_existing_embedding(db):
    report = make_report(db)

    original = save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=[0.1, 0.2, 0.3],
        model_name="test-model",
    )

    updated = save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=[0.4, 0.5, 0.6],
        model_name="test-model",
    )

    assert updated.id == original.id
    assert updated.vector == [0.4, 0.5, 0.6]

    statement = select(ItemEmbedding).where(
        ItemEmbedding.report_id == report.id,
        ItemEmbedding.embedding_type == "text",
        ItemEmbedding.model_name == "test-model",
        ItemEmbedding.image_id.is_(None),
    )

    assert len(db.scalars(statement).all()) == 1


def test_embeddings_for_different_models_are_separate(db):
    report = make_report(db)

    save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=[0.1, 0.2],
        model_name="model-a",
    )

    save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=[0.7, 0.8],
        model_name="model-b",
    )

    result_a = get_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        model_name="model-a",
    )

    result_b = get_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        model_name="model-b",
    )

    assert result_a == [0.1, 0.2]
    assert result_b == [0.7, 0.8]


def test_save_embedding_rejects_empty_vector(db):
    report = make_report(db)

    with pytest.raises(ValueError, match="empty embedding"):
        save_embedding(
            db=db,
            report_id=report.id,
            embedding_type="text",
            vector=[],
            model_name="test-model",
        )
