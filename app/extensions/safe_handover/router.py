"""FastAPI router for Safe Handover Finder endpoints."""

from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query, status

from app.core import config
from app.extensions.safe_handover.providers import default_provider
from app.extensions.safe_handover.schemas import (
    CategoryMetadata,
    GeocodeResult,
    GeocodeSearchResponse,
    HandoverLocation,
    HandoverSearchRequest,
    HandoverSearchResponse,
    TravelContext,
)
from app.extensions.safe_handover.service import (
    CATEGORY_METADATA_LIST,
    default_service,
    get_campus_location,
)

router = APIRouter(
    prefix="/api/handover",
    tags=["Safe Handover"],
)


@router.post(
    "/nearby",
    response_model=HandoverSearchResponse,
    summary="Find nearby safe handover locations (POST)",
    description="Retrieve and rank verified nearby police stations, lost property offices, and handover points.",
)
async def find_nearby_handovers_post(
    request: HandoverSearchRequest,
) -> HandoverSearchResponse:
    """Find nearby safe handover locations given GPS coordinates and search criteria."""
    try:
        return await default_service.search_nearby_handovers(request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching nearby handover locations: {str(exc)}",
        )


@router.get(
    "/nearby",
    response_model=HandoverSearchResponse,
    summary="Find nearby safe handover locations (GET)",
    description="Query-parameter-based interface for nearby handover location discovery.",
)
async def find_nearby_handovers_get(
    lat: float = Query(..., description="Latitude (-90 to 90)"),
    lon: float = Query(..., description="Longitude (-180 to 180)"),
    radius_km: float = Query(5.0, gt=0.0, le=50.0, description="Search radius in kilometers"),
    category: str = Query("all", description="Facility category filter"),
    travel_context: str = Query("general", description="Travel mode (walking_city, train_travel, road_travel, airport_travel, campus, general)"),
    limit: int = Query(20, ge=1, le=50, description="Maximum number of results"),
) -> HandoverSearchResponse:
    """Find nearby safe handover locations using query parameters."""
    if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Latitude must be between -90 and 90, and longitude between -180 and 180 degrees.",
        )

    req = HandoverSearchRequest(
        latitude=lat,
        longitude=lon,
        radius_km=radius_km,
        category=category,
        travel_context=travel_context,
        limit=limit,
    )
    try:
        return await default_service.search_nearby_handovers(req)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error searching nearby handover locations: {str(exc)}",
        )


@router.get(
    "/geocode",
    response_model=GeocodeSearchResponse,
    summary="Geocode address, city, or landmark",
    description="Search place names and addresses to obtain geographic coordinates.",
)
async def geocode_location(
    q: str = Query(..., min_length=1, description="Place, city, or landmark query string"),
    limit: int = Query(5, ge=1, le=10, description="Max results"),
) -> GeocodeSearchResponse:
    """Resolve human-readable place query into GPS coordinates using Nominatim."""
    results = await default_provider.geocode(query=q, limit=limit)
    return GeocodeSearchResponse(
        query=q,
        results=results,
    )


@router.get(
    "/categories",
    response_model=List[CategoryMetadata],
    summary="List supported handover categories",
    description="Returns metadata and descriptions for all supported facility categories.",
)
def get_handover_categories() -> List[CategoryMetadata]:
    """Return supported handover categories with policy tiers and descriptions."""
    return CATEGORY_METADATA_LIST


@router.get(
    "/campus",
    response_model=HandoverLocation,
    summary="Get campus security handover location",
    description="Returns verified institutional lost-and-found desk details for the primary college campus.",
)
def get_campus_handover_desk() -> HandoverLocation:
    """Return the configured primary campus handover desk."""
    return get_campus_location(
        user_lat=config.CAMPUS_LATITUDE,
        user_lon=config.CAMPUS_LONGITUDE,
        travel_context=TravelContext.CAMPUS,
    )
