"""Pydantic schemas for Guest Finder, Anonymous Reporting, and Transit Recovery."""

from datetime import date, datetime
from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


JourneyType = Literal[
    "auto_rickshaw",
    "taxi",
    "train",
    "bus",
    "metro",
    "flight",
    "walking",
    "other",
]

ContactMethod = Literal[
    "email",
    "phone",
    "none",
]


class GuestFoundReportCreate(BaseModel):
    """Schema for a guest finder reporting a found item without an account."""
    item_name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(
        min_length=5,
        max_length=2000,
        description="Public description of the item (do not include sensitive internal contents).",
    )
    color: Optional[str] = Field(default=None, max_length=50)
    brand: Optional[str] = Field(default=None, max_length=100)
    model: Optional[str] = Field(default=None, max_length=100)

    # Location & Date
    location_text: str = Field(min_length=2, max_length=255)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    event_date: Optional[date] = None
    approximate_time: Optional[str] = Field(default=None, max_length=50)

    # Journey context
    journey_type: Optional[str] = Field(default=None, max_length=50)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    dropoff_location: Optional[str] = Field(default=None, max_length=255)
    vehicle_identifier: Optional[str] = Field(default=None, max_length=100)
    route_notes: Optional[str] = Field(default=None, max_length=1000)

    # Privacy & Contact
    is_anonymous: bool = Field(default=False)
    contact_method: ContactMethod = Field(default="none")
    contact_value: Optional[str] = Field(default=None, max_length=255)

    # Ownership Protection (Private details NOT exposed publicly)
    private_contents: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Private interior bag contents or non-obvious details used exclusively for claimant verification.",
    )
    distinctive_marks: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Private distinctive markings, scratches, or stickers.",
    )

    # QR source & Handover preference
    qr_source: Optional[str] = Field(default=None, max_length=100)
    preferred_handover_mode: Optional[str] = Field(
        default="official_facility",
        max_length=50,
        description="Preferred handover mode: 'official_facility', 'staffed_public_desk', or 'undecided'.",
    )
    handover_facility_name: Optional[str] = Field(default=None, max_length=255)

    @field_validator("item_name", "category", "description", "location_text", mode="before")
    @classmethod
    def strip_text(cls, val):
        if isinstance(val, str):
            return val.strip()
        return val


class GuestLostReportCreate(BaseModel):
    """Schema for a passenger reporting a lost item without knowing the driver."""
    item_name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=5, max_length=2000)
    color: Optional[str] = Field(default=None, max_length=50)
    brand: Optional[str] = Field(default=None, max_length=100)
    model: Optional[str] = Field(default=None, max_length=100)

    location_text: str = Field(min_length=2, max_length=255)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    event_date: Optional[date] = None
    approximate_time: Optional[str] = Field(default=None, max_length=50)

    # Journey context
    journey_type: Optional[str] = Field(default=None, max_length=50)
    pickup_location: Optional[str] = Field(default=None, max_length=255)
    dropoff_location: Optional[str] = Field(default=None, max_length=255)
    vehicle_identifier: Optional[str] = Field(default=None, max_length=100)
    route_notes: Optional[str] = Field(default=None, max_length=1000)

    # Contact
    contact_method: ContactMethod = Field(default="email")
    contact_value: Optional[str] = Field(default=None, max_length=255)

    # Distinctive features & ownership proof
    private_contents: Optional[str] = Field(default=None, max_length=2000)
    distinctive_marks: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("item_name", "category", "description", "location_text", mode="before")
    @classmethod
    def strip_text(cls, val):
        if isinstance(val, str):
            return val.strip()
        return val


class GuestReportReceipt(BaseModel):
    """Secure receipt issued to the guest after submitting a report."""
    case_reference: str
    secret_key: str
    report_id: int
    guest_role: str
    item_name: str
    category: str
    is_anonymous: bool
    journey_type: Optional[str] = None
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    created_at: datetime
    tracking_url: str
    handover_advice: str
    safety_guidance: str


class PublicReportSafeView(BaseModel):
    """Sanitized public representation of a report with sensitive ownership details omitted."""
    id: int
    report_type: str
    item_name: str
    category: str
    color: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    description: str
    event_date: date
    location_text: str
    journey_type: Optional[str] = None
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    approximate_time: Optional[str] = None
    image_count: int = 0
    status: str


class CoordinationMessageCreate(BaseModel):
    message_text: str = Field(min_length=1, max_length=1000)
    is_safe_location_suggestion: bool = False


class CoordinationMessageResponse(BaseModel):
    id: int
    sender_role: str
    message_text: str
    is_safe_location_suggestion: bool
    created_at: datetime


class HandoverCodeGenerateRequest(BaseModel):
    claim_id: int
    agreed_location_type: str = Field(
        description="Type: police_station, station_desk, campus_security, or staffed_public_desk"
    )
    agreed_location_name: str = Field(min_length=3, max_length=255)
    agreed_location_address: Optional[str] = Field(default=None, max_length=500)


class HandoverCodeResponse(BaseModel):
    handover_code: str
    claim_id: int
    status: str
    agreed_location_type: str
    agreed_location_name: str
    agreed_location_address: Optional[str] = None
    instructions: str


class HandoverConfirmationRequest(BaseModel):
    handover_code: str = Field(min_length=4, max_length=32)
    confirmed_by: Literal["finder", "claimant"]
    notes: Optional[str] = Field(default=None, max_length=500)


class HandoverConfirmationResponse(BaseModel):
    success: bool
    handover_code: str
    status: str
    completed_at: Optional[datetime] = None
    message: str


class AccountLinkRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    full_name: Optional[str] = Field(default=None, max_length=120)


class AccountLinkResponse(BaseModel):
    success: bool
    case_reference: str
    linked_account_email: str
    reward_eligibility: str
    message: str


class GuestCaseDetailResponse(BaseModel):
    """Full authenticated view for the guest (requiring case_reference and secret_key)."""
    case_reference: str
    report_id: int
    guest_role: str
    item_name: str
    category: str
    color: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    public_description: str
    location_text: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    event_date: date
    approximate_time: Optional[str] = None
    journey_type: Optional[str] = None
    pickup_location: Optional[str] = None
    dropoff_location: Optional[str] = None
    vehicle_identifier: Optional[str] = None
    route_notes: Optional[str] = None
    is_anonymous: bool
    contact_method: Optional[str] = None
    contact_value: Optional[str] = None
    private_contents: Optional[str] = None
    distinctive_marks: Optional[str] = None
    preferred_handover_mode: Optional[str] = None
    handover_facility_name: Optional[str] = None
    linked_account_email: Optional[str] = None
    report_status: str
    created_at: datetime
    images: list[str] = []
    messages: list[CoordinationMessageResponse] = []
    active_handover: Optional[HandoverCodeResponse] = None
    suggested_handover_facilities: list[dict] = []


class TransitQRConfigResponse(BaseModel):
    provider_id: str
    provider_name: str
    hub_name: str
    destination_url: str
    qr_svg: str
    safety_notice: str
