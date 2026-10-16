"""API Router for Campus Location Selection and Zone Directory."""

from fastapi import APIRouter
from app.extensions.campus.locations import get_all_campus_locations
from app.extensions.campus.schemas import CampusLocationsResponse

router = APIRouter(
    prefix="/api/campus",
    tags=["Campus Directory & Locations"],
)


@router.get(
    "/locations",
    response_model=CampusLocationsResponse,
    summary="Get verified campus locations and intake points",
    description="Returns verified campus buildings, zones, coordinates, and operating hours for lost property selection.",
)
def list_campus_locations_endpoint():
    """List all available campus zones, buildings, and lost-property desks."""
    return get_all_campus_locations()
