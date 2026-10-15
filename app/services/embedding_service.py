
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ItemEmbedding


def get_embedding(
    db: Session,
    report_id: int,
    embedding_type: str,
    image_id: int | None = None,
    model_name: str | None = None,
) -> list[float] | None:
    """Retrieve an embedding for a specific report and model."""

    statement = select(ItemEmbedding).where(
        ItemEmbedding.report_id == report_id,
        ItemEmbedding.embedding_type == embedding_type,
        ItemEmbedding.image_id == image_id,
    )

    if model_name is not None:
        statement = statement.where(
            ItemEmbedding.model_name == model_name
        )

    record = db.scalars(statement).first()

    if record is None:
        return None

    return record.vector





def save_embedding(
    db: Session,
    report_id: int,
    embedding_type: str,
    vector: list[float],
    model_name: str,
    image_id: int | None = None,
) -> None:
    """Insert or update an embedding record."""
    statement = select(ItemEmbedding).where(
        ItemEmbedding.report_id == report_id,
        ItemEmbedding.embedding_type == embedding_type,
        ItemEmbedding.image_id == image_id,
    )

    record = db.scalars(statement).first()

    if record is None:
        record = ItemEmbedding(
            report_id=report_id,
            image_id=image_id,
            embedding_type=embedding_type,
            vector=vector,
            model_name=model_name,
        )
        db.add(record)
    else:
        record.vector = vector
        record.model_name = model_name

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
