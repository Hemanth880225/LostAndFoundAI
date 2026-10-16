"""Schemas for Verified Claims and Ownership Evidence."""

from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VerificationStatus(str, Enum):
    """Auditable lifecycle statuses for verified claims."""
    SUBMITTED = "submitted"
    CONTACT_VERIFICATION_PENDING = "contact_verification_pending"
    UNDER_REVIEW = "under_review"
    ADDITIONAL_INFORMATION_REQUIRED = "additional_information_required"
    APPROVED = "approved"
    REJECTED = "rejected"
    HANDOVER_PENDING = "handover_pending"
    COMPLETED = "completed"
    SUSPECTED_FRAUD_REVIEW = "suspected_fraud_review"


class EvidenceType(str, Enum):
    """Classified ownership evidence categories."""
    SERIAL_NUMBER = "serial_number"
    IDENTIFYING_FEATURE = "identifying_feature"
    PURCHASE_RECEIPT = "purchase_receipt"
    ORIGINAL_PHOTO = "original_photo"
    OWNERSHIP_DOCUMENT = "ownership_document"
    ACCESSORY_DETAIL = "accessory_detail"
    OTHER = "other"


class VerifiedClaimCreate(BaseModel):
    """Payload for submitting a verified claim with ownership evidence."""
    lost_report_id: int = Field(gt=0, description="ID of the user's lost item report")
    claimant_name: str = Field(min_length=2, max_length=120, description="Full legal or campus name")
    contact_email: EmailStr = Field(description="Contact email address")
    contact_phone: Optional[str] = Field(default=None, max_length=30, description="Optional phone number")
    claim_message: str = Field(min_length=10, max_length=2000, description="Explanation of ownership")
    serial_number: Optional[str] = Field(default=None, max_length=100, description="Serial number or hardware UUID if known")
    identifying_features: Optional[str] = Field(default=None, max_length=1000, description="Distinctive private features not in public report")
    distinctive_marks: Optional[str] = Field(default=None, max_length=1000, description="Scratches, stickers, or unique contents")
    privacy_consent: bool = Field(default=True, description="Consent to the lawful handling and verification of submitted information")


class AdditionalInfoSubmission(BaseModel):
    """Payload for responding to a reviewer's request for additional evidence."""
    additional_info: str = Field(min_length=5, max_length=2000, description="Supplementary details or answers requested by reviewer")


class EvidenceItemResponse(BaseModel):
    """Safe metadata representation of an uploaded evidence file."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    claim_id: int
    evidence_type: str
    description: str
    original_filename: Optional[str] = None
    file_size_bytes: Optional[int] = None
    is_sensitive: bool = False
    created_at: datetime


class VerifiedClaimResponse(BaseModel):
    """Publicly safe representation of a verified claim."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    lost_report_id: int
    found_report_id: int
    claimant_name: str
    contact_email: str
    contact_phone: Optional[str] = None
    phone_verified: bool = False
    email_verified: bool = False
    verification_method: str = "unverified"
    status: str
    verification_status: str
    created_at: datetime
    evidence_count: int = 0
    additional_info_requested: Optional[str] = None
    public_status_message: str = "Claim submitted and pending review."
