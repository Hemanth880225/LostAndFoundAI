"""Pre-configured verified College Campus locations and Lost-and-Found intake points."""

from app.core import config
from app.extensions.campus.schemas import CampusLocationItem, CampusLocationsResponse


CAMPUS_LOCATIONS = [
    CampusLocationItem(
        id="campus-security-hq",
        name="Main Administrative Building — Security Command Desk",
        building_code="ADM-01",
        zone="Central Zone",
        latitude=config.CAMPUS_LATITUDE,
        longitude=config.CAMPUS_LONGITUDE,
        description="24/7 central campus lost-and-found intake command and custody desk.",
        has_lost_property_drop=True,
        operating_hours="24/7 (Always Open)",
    ),
    CampusLocationItem(
        id="campus-library-central",
        name="Central University Library — Circulation Desk",
        building_code="LIB-01",
        zone="Academic Zone",
        latitude=config.CAMPUS_LATITUDE + 0.0012,
        longitude=config.CAMPUS_LONGITUDE + 0.0008,
        description="Circulation desk on Ground Floor; holds items found in study cubicles and reading halls.",
        has_lost_property_drop=True,
        operating_hours="08:00 AM – 10:00 PM",
    ),
    CampusLocationItem(
        id="campus-cs-it-block",
        name="Computer Science & Engineering Block — Labs Foyer",
        building_code="CSE-02",
        zone="Engineering Zone",
        latitude=config.CAMPUS_LATITUDE - 0.0015,
        longitude=config.CAMPUS_LONGITUDE + 0.0010,
        description="Ground floor reception desk near computer laboratories 1 to 4.",
        has_lost_property_drop=True,
        operating_hours="08:30 AM – 06:30 PM",
    ),
    CampusLocationItem(
        id="campus-student-center",
        name="Student Activity Center & Main Cafeteria",
        building_code="SAC-01",
        zone="Student Life Zone",
        latitude=config.CAMPUS_LATITUDE + 0.0020,
        longitude=config.CAMPUS_LONGITUDE - 0.0014,
        description="Student services counter outside food court dining area.",
        has_lost_property_drop=True,
        operating_hours="07:30 AM – 09:30 PM",
    ),
    CampusLocationItem(
        id="campus-sports-complex",
        name="Campus Sports Complex & Indoor Gymnasium",
        building_code="SPT-01",
        zone="Athletics Zone",
        latitude=config.CAMPUS_LATITUDE - 0.0025,
        longitude=config.CAMPUS_LONGITUDE - 0.0020,
        description="Equipment intake counter and sports pavilion reception desk.",
        has_lost_property_drop=True,
        operating_hours="06:00 AM – 08:30 PM",
    ),
    CampusLocationItem(
        id="campus-lecture-complex",
        name="Lecture Hall Complex — Hall 1 to 8 Foyer",
        building_code="LHC-01",
        zone="Academic Zone",
        latitude=config.CAMPUS_LATITUDE + 0.0005,
        longitude=config.CAMPUS_LONGITUDE - 0.0005,
        description="Caregiver and housekeeping help post outside major lecture auditoriums.",
        has_lost_property_drop=True,
        operating_hours="08:00 AM – 07:00 PM",
    ),
]


def get_all_campus_locations() -> CampusLocationsResponse:
    """Return the registry of configured campus buildings and lost-property desks."""
    return CampusLocationsResponse(
        campus_name=config.CAMPUS_NAME,
        city=config.CAMPUS_CITY,
        locations=CAMPUS_LOCATIONS,
    )
