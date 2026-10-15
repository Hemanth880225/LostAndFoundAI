
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base

from sqlalchemy import ForeignKey, JSON
from sqlalchemy import String

from sqlalchemy import ForeignKey




class ItemReport(Base):
    __tablename__ = "item_reports"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    report_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )

    item_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    category: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        index=True,
    )

    color: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    brand: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    event_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True,
    )

    location_text: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    latitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    longitude: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )




class ItemImage(Base):
    __tablename__ = "item_images"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
        index=True,
    )

    image_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    content_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )





class ItemEmbedding(Base):
    __tablename__ = "item_embeddings"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
        index=True,
    )

    image_id: Mapped[int | None] = mapped_column(
        ForeignKey("item_images.id"),
        nullable=True,
        index=True,
    )

    embedding_type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )

    vector: Mapped[list[float]] = mapped_column(
        JSON,
        nullable=False,
    )

    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )






class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    lost_report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
        index=True,
    )

    found_report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
        index=True,
    )

    claimant_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    contact_email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
    )

    claim_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )
