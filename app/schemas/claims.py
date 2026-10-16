
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)


class ClaimCreate(BaseModel):
    """Validate a new claim submitted by a user."""

    lost_report_id: int = Field(gt=0)

    claimant_name: str = Field(
        min_length=2,
        max_length=120,
    )

    contact_email: EmailStr

    claim_message: str = Field(
        min_length=10,
        max_length=2000,
    )


class ClaimResponse(BaseModel):
    """Define the safe public response for a claim."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    lost_report_id: int
    found_report_id: int
    claimant_name: str
    status: str
    created_at: datetime


class ClaimReview(BaseModel):
    """Validate an authorized review decision."""

    status: Literal["approved", "rejected"]

    review_note: str = Field(
        min_length=5,
        max_length=1000,
    )


class HandoverRequest(BaseModel):
    """Validate the details recorded for a handover."""

    handover_note: str = Field(
        min_length=5,
        max_length=1000,
    )
