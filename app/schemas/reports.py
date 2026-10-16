
from datetime import date, datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class ItemImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    report_id: int
    image_path: str
    original_filename: str | None = None
    content_type: str
    created_at: datetime

    @computed_field
    @property
    def url(self) -> str:
        if self.image_path.startswith("/"):
            return self.image_path
        return f"/{self.image_path}"


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

    @field_validator(
        "item_name",
        "category",
        "description",
        "location_text",
        mode="before",
    )
    @classmethod
    def validate_required_text(cls, value):
        if isinstance(value, str):
            value = value.strip()

            if not value:
                raise ValueError("This field cannot be blank.")

        return value

    @field_validator(
        "color",
        "brand",
        "model",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None

        return value

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
    images: list[ItemImageResponse] = Field(default_factory=list)

