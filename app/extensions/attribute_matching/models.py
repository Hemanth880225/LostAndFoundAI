"""SQLAlchemy database model for persisting extracted and user-confirmed item attributes."""

from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class ItemAttributeRecord(Base):
    """
    Persisted visual, physical, and functional attributes for an ItemReport.
    Maintains clean 1-to-1 association with item_reports without altering core table schema.
    """
    __tablename__ = "item_attributes"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    report_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("item_reports.id"),
        unique=True,
        nullable=False,
        index=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
    )

    primary_color: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    secondary_color: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    is_multicolor: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )

    shape: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
    )

    size_category: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    dimensions_text: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    capacity_litres: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    capacity_text: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    material: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    patterns: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    distinctive_features: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )

    confidence_scores: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    raw_attributes: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
