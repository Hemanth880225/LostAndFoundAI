"""Schemas for Campus Location Selection and Zones."""

from typing import List, Optional
from pydantic import BaseModel, Field


class CampusLocationItem(BaseModel):
    id: str
    name: str
    building_code: str
    zone: str
    latitude: float
    longitude: float
    description: str
    has_lost_property_drop: bool = True
    operating_hours: str = "08:00 AM – 08:00 PM"


class CampusLocationsResponse(BaseModel):
    campus_name: str
    city: str
    locations: List[CampusLocationItem]
