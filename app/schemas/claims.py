
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ClaimCreate(BaseModel):
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
    model_config = ConfigDict(from_attributes=True)

    id: int
    lost_report_id: int
    found_report_id: int
    claimant_name: str
    status: str
    created_at: datetime
