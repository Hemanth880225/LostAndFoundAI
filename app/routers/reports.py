
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


from fastapi import APIRouter

router = APIRouter(
    prefix="/api/reports",
    tags=["Reports"],
)



class ItemReportCreate(BaseModel):
    report_type: Literal["lost", "found"]
    item_name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)

    color: str | None = Field(default=None, max_length=50)
    brand: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)

    description: str = Field(min_length=5, max_length=2000)
    event_date: date
    location_text: str = Field(min_length=2, max_length=255)

    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_coordinates(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "Latitude and longitude must be provided together."
            )
        return self


class ItemReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_type: Literal["lost", "found"]
    item_name: str
    category: str
    color: str | None
    brand: str | None
    model: str | None
    description: str
    event_date: date
    location_text: str
    latitude: float | None
    longitude: float | None
    status: str
    created_at: datetime
