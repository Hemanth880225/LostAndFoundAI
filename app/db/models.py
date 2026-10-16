
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base





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

    images: Mapped[list["ItemImage"]] = relationship(
        "ItemImage",
        back_populates="report",
        cascade="all, delete-orphan",
        order_by="ItemImage.id",
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

    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
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

    report: Mapped["ItemReport"] = relationship(
        "ItemReport",
        back_populates="images",
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






class ClaimReviewRecord(Base):
    __tablename__ = "claim_review_records"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
        index=True,
    )

    decision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    review_note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    reviewer_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )




class ClaimHandoverRecord(Base):
    __tablename__ = "claim_handover_records"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
        unique=True,
        index=True,
    )

    handover_note: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    reviewer_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    handed_over_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )


class ClaimVerificationDetail(Base):
    __tablename__ = "claim_verification_details"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        unique=True,
        index=True,
        nullable=False,
    )

    verification_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="submitted",
        index=True,
    )

    contact_phone: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    phone_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    email_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    verification_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="unverified",
    )

    serial_number: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    identifying_features: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    distinctive_marks: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    privacy_consent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    additional_info_requested: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    additional_info_provided: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    fraud_flag_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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


class ClaimEvidence(Base):
    __tablename__ = "claim_evidence"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
        index=True,
    )

    evidence_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    file_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    file_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    file_size_bytes: Mapped[int | None] = mapped_column(
        nullable=True,
    )

    is_sensitive: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )


class EvidenceAuditLog(Base):
    __tablename__ = "evidence_audit_logs"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
        index=True,
    )

    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("claim_evidence.id"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    actor_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    timestamp: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )


class RewardLedger(Base):
    __tablename__ = "reward_ledger"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    transaction_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        index=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
    )

    recipient_email: Mapped[str] = mapped_column(
        String(254),
        nullable=False,
        index=True,
    )

    recipient_name: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    found_report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
        index=True,
    )

    points: Mapped[int] = mapped_column(
        nullable=False,
    )

    reward_rupees: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    verified_item_value: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    reward_rate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    points_per_rupee: Mapped[int] = mapped_column(
        nullable=False,
        default=5,
    )

    transaction_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="recovery_reward",
        index=True,
    )

    reviewer_label: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    reversal_ref: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )

    notes: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )


class PoliceComplaintDraft(Base):
    __tablename__ = "police_complaint_drafts"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    draft_reference: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        index=True,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        nullable=False,
        index=True,
    )

    found_report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
    )

    lost_report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        nullable=False,
    )

    incident_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    fraud_indicators: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    event_timeline: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    shareable_contact_info: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    reviewer_observations: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    prepared_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="draft_pending_human_submission",
    )

    police_station_target: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    official_fir_reference: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
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


class GuestRecoveryReport(Base):
    __tablename__ = "guest_recovery_reports"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    report_id: Mapped[int] = mapped_column(
        ForeignKey("item_reports.id"),
        unique=True,
        index=True,
        nullable=False,
    )

    case_reference: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
        nullable=False,
    )

    secret_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    guest_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="finder",
    )

    is_anonymous: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    contact_method: Mapped[str | None] = mapped_column(
        String(30),
        nullable=True,
    )

    contact_value: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    journey_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    pickup_location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    dropoff_location: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    vehicle_identifier: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    route_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    approximate_time: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    private_contents: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    distinctive_marks: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    qr_source: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    preferred_handover_mode: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    handover_facility_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    linked_account_email: Mapped[str | None] = mapped_column(
        String(254),
        nullable=True,
    )

    linked_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
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

    report: Mapped["ItemReport"] = relationship("ItemReport")


class GuestCoordinationMessage(Base):
    __tablename__ = "guest_coordination_messages"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    guest_report_id: Mapped[int] = mapped_column(
        ForeignKey("guest_recovery_reports.id"),
        index=True,
        nullable=False,
    )

    claim_id: Mapped[int | None] = mapped_column(
        ForeignKey("claims.id"),
        index=True,
        nullable=True,
    )

    sender_role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    message_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    is_safe_location_suggestion: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )


class GuestHandoverVerification(Base):
    __tablename__ = "guest_handover_verifications"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True,
    )

    guest_report_id: Mapped[int] = mapped_column(
        ForeignKey("guest_recovery_reports.id"),
        unique=True,
        index=True,
        nullable=False,
    )

    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id"),
        index=True,
        nullable=False,
    )

    handover_code: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="code_issued",
    )

    agreed_location_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    agreed_location_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    agreed_location_address: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    confirmed_by_finder: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    confirmed_by_claimant: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
    )



