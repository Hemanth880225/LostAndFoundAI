
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ItemEmbedding


def get_embedding(
    db: Session,
    report_id: int,
    embedding_type: str,
    model_name: str,
    image_id: int | None = None,
) -> list[float] | None:
    """
    Retrieve an existing embedding for a report or one of its images.
    Return None if no matching embedding exists.
    """

    statement = select(ItemEmbedding).where(
        ItemEmbedding.report_id == report_id,
        ItemEmbedding.embedding_type == embedding_type,
        ItemEmbedding.model_name == model_name,
        ItemEmbedding.image_id == image_id,
    )

    embedding = db.scalars(statement).first()

    if embedding is None:
        return None

    return embedding.vector


def save_embedding(
    db: Session,
    report_id: int,
    embedding_type: str,
    vector: list[float],
    model_name: str,
    image_id: int | None = None,
) -> ItemEmbedding:
    """
    Save an embedding or update the existing matching record.
    """

    if not vector:
        raise ValueError("Cannot save an empty embedding.")

    statement = select(ItemEmbedding).where(
        ItemEmbedding.report_id == report_id,
        ItemEmbedding.embedding_type == embedding_type,
        ItemEmbedding.model_name == model_name,
        ItemEmbedding.image_id == image_id,
    )

    embedding = db.scalars(statement).first()

    try:
        if embedding is None:
            embedding = ItemEmbedding(
                report_id=report_id,
                image_id=image_id,
                embedding_type=embedding_type,
                vector=vector,
                model_name=model_name,
            )
            db.add(embedding)
        else:
            embedding.vector = vector

        db.commit()
        db.refresh(embedding)

    except Exception:
        db.rollback()
        raise

    return embedding
