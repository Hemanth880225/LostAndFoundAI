"""Pydantic schemas for the Safe Handover Finder extension."""

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class HandoverCategory(str, Enum):
    """Recognized handover facility categories."""
    ALL = "all"
    POLICE = "police"
    LOST_PROPERTY = "lost_property"
    TRANSIT = "transit"
    CAMPUS_SECURITY = "campus_security"
    PUBLIC_SERVICE = "public_service"
    POST_OFFICE = "post_office"


class TravelContext(str, Enum):
    """User-selected travel contexts to assist relevance scoring."""
    GENERAL = "general"
    WALKING_CITY = "walking_city"
    ROAD_TRAVEL = "road_travel"
    TRAIN_TRAVEL = "train_travel"
    AIRPORT_TRAVEL = "airport_travel"
    CAMPUS = "campus"


class AcceptanceStatus(str, Enum):
    """Confidence level of property handover acceptance at the location."""
    LIKELY = "likely"
    REQUIRES_STAFF_INQUIRY = "requires_staff_inquiry"
    UNCONFIRMED = "unconfirmed"


class RecommendationTier(str, Enum):
    """Recommendation priority tier based on facility role and verified mandate."""
    PRIMARY = "primary"
    SECONDARY = "secondary"
    CONDITIONAL = "conditional"


class HandoverLocation(BaseModel):
    """A verified or discovered nearby safe handover location."""
    id: str = Field(..., description="Unique identifier for the location")
    name: str = Field(..., description="Official or common name of the facility")
    category: HandoverCategory = Field(..., description="Standardized category")
    category_label: str = Field(..., description="Human-readable category label")
    latitude: float = Field(..., description="Geographic latitude")
    longitude: float = Field(..., description="Geographic longitude")
    address: str = Field(..., description="Physical address or location description")
    city: Optional[str] = Field(default=None, description="City or municipality")
    distance_km: float = Field(..., description="Straight-line distance in kilometers")
    distance_label: str = Field(..., description="Clear label indicating straight-line distance")
    phone: Optional[str] = Field(default=None, description="Verified contact phone if available")
    operating_hours: Optional[str] = Field(default=None, description="Operating hours if available")
    acceptance_status: AcceptanceStatus = Field(..., description="Acceptance policy status")
    acceptance_note: str = Field(..., description="Clear explanation of acceptance policies and caveats")
    recommendation_tier: RecommendationTier = Field(..., description="Priority recommendation tier")
    recommendation_reason: str = Field(..., description="Transparent basis for this location's ranking")
    score: float = Field(..., description="Computed composite relevance score")
    source: str = Field(..., description="Data source (e.g. OpenStreetMap / Campus Registry)")
    directions_url_google: str = Field(..., description="External Google Maps directions URL")
    directions_url_osm: str = Field(..., description="External OpenStreetMap directions URL")


class HandoverSearchRequest(BaseModel):
    """Request payload for finding nearby handover locations."""
    latitude: float = Field(..., ge=-90.0, le=90.0, description="User latitude")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="User longitude")
    radius_km: float = Field(default=5.0, gt=0.0, le=50.0, description="Search radius in kilometers")
    category: Optional[str] = Field(default="all", description="Facility category filter")
    travel_context: Optional[str] = Field(default="general", description="Travel mode or environment")
    limit: int = Field(default=20, ge=1, le=50, description="Maximum results to return")


class HandoverSearchResponse(BaseModel):
    """Response payload containing nearby handover locations and context."""
    query_latitude: float
    query_longitude: float
    query_address: Optional[str] = None
    search_radius_km: float
    travel_context: str
    total_found: int
    locations: List[HandoverLocation]
    safety_disclaimer: str


class GeocodeResult(BaseModel):
    """A geocoded place result from Nominatim or address resolver."""
    display_name: str
    latitude: float
    longitude: float
    place_type: Optional[str] = None
    importance: Optional[float] = None


class GeocodeSearchResponse(BaseModel):
    """Response containing geocoded location candidates."""
    query: str
    results: List[GeocodeResult]


class CategoryMetadata(BaseModel):
    """Metadata for category options shown in the frontend."""
    id: str
    label: str
    description: str
    tier: RecommendationTier
