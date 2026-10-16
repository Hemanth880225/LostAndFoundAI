"""Service layer for safe handover location retrieval, ranking, and validation."""

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from app.core import config
from app.extensions.safe_handover.providers import BaseLocationProvider, default_provider
from app.extensions.safe_handover.schemas import (
    AcceptanceStatus,
    CategoryMetadata,
    HandoverCategory,
    HandoverLocation,
    HandoverSearchRequest,
    HandoverSearchResponse,
    RecommendationTier,
    TravelContext,
)

SAFETY_DISCLAIMER = (
    "Safety Disclaimer: Handover recommendations are derived from verified public facility registries "
    "and OpenStreetMap directory data. The application does not guarantee that any specific facility is "
    "currently open, staffed, or able to accept personal items. Never put yourself at risk. If an item appears "
    "dangerous, hazardous, or suspicious, DO NOT handle or transport it — immediately notify local emergency "
    "authorities. In any emergency, contact your regional emergency dispatch service (e.g. 112 / 999 / 911). "
    "Always speak with on-duty staff before depositing found property."
)

CATEGORY_METADATA_LIST = [
    CategoryMetadata(
        id="all",
        label="All Handover Points",
        description="Comprehensive list of official and public handover locations nearby.",
        tier=RecommendationTier.PRIMARY,
    ),
    CategoryMetadata(
        id="police",
        label="Police Stations",
        description="Official law enforcement desks with statutory custody procedures.",
        tier=RecommendationTier.PRIMARY,
    ),
    CategoryMetadata(
        id="campus_security",
        label="Campus Security",
        description="Institutional command desks for property found on or near campus.",
        tier=RecommendationTier.PRIMARY,
    ),
    CategoryMetadata(
        id="lost_property",
        label="Lost Property Offices",
        description="Dedicated public lost-and-found intake counters.",
        tier=RecommendationTier.PRIMARY,
    ),
    CategoryMetadata(
        id="transit",
        label="Transit Desks & Hubs",
        description="Railway and airport customer assistance desks (staff inquiry recommended).",
        tier=RecommendationTier.SECONDARY,
    ),
    CategoryMetadata(
        id="public_service",
        label="Civic & Municipal Desks",
        description="Town halls, civic centers, and public inquiry desks.",
        tier=RecommendationTier.SECONDARY,
    ),
    CategoryMetadata(
        id="post_office",
        label="Post Offices (Staff Inquiry)",
        description="Postal facilities (Note: counter inquiry required; items not accepted automatically).",
        tier=RecommendationTier.CONDITIONAL,
    ),
]


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate straight-line distance in kilometers between two GPS coordinates using the Haversine formula."""
    if lat1 == lat2 and lon1 == lon2:
        return 0.0

    r = 6371.0088  # Earth mean radius in kilometers
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(r * c, 2)


def generate_google_directions_url(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> str:
    """Build external Google Maps navigation URL."""
    return f"https://www.google.com/maps/dir/?api=1&origin={origin_lat:.6f},{origin_lon:.6f}&destination={dest_lat:.6f},{dest_lon:.6f}"


def generate_osm_directions_url(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> str:
    """Build external OpenStreetMap directions URL."""
    return f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_car&route={origin_lat:.6f},{origin_lon:.6f}%3B{dest_lat:.6f},{dest_lon:.6f}"


def classify_category(raw_item: Dict[str, Any]) -> HandoverCategory:
    """Determine standardized HandoverCategory from raw OSM tags and item name."""
    type_str = str(raw_item.get("type", "")).lower()
    cat_str = str(raw_item.get("category", "")).lower()
    name_str = str(raw_item.get("name", "")).lower()
    disp_str = str(raw_item.get("display_name", "")).lower()

    combined = f"{type_str} {cat_str} {name_str} {disp_str}"

    if "police" in combined or "chowki" in combined or "thana" in combined or "gendarmerie" in combined:
        return HandoverCategory.POLICE
    if "lost property" in combined or "lost and found" in combined:
        return HandoverCategory.LOST_PROPERTY
    if "campus security" in combined or "university security" in combined:
        return HandoverCategory.CAMPUS_SECURITY
    if any(k in combined for k in ["railway station", "train station", "metro station", "bus station", "bus terminal", "airport", "aerodrome"]):
        return HandoverCategory.TRANSIT
    if "post_office" in type_str or "post office" in combined or "dak ghar" in combined:
        return HandoverCategory.POST_OFFICE
    if any(k in combined for k in ["town hall", "townhall", "civic centre", "city hall", "courthouse", "municipal"]):
        return HandoverCategory.PUBLIC_SERVICE

    return HandoverCategory.PUBLIC_SERVICE


def evaluate_acceptance(
    category: HandoverCategory,
    name: str,
    extratags: Optional[Dict[str, Any]] = None,
) -> Tuple[AcceptanceStatus, str, RecommendationTier, str]:
    """Evaluate acceptance policy, caveat note, recommendation tier, and transparent rationale."""
    tags = extratags or {}

    if category == HandoverCategory.POLICE:
        return (
            AcceptanceStatus.LIKELY,
            "Official law enforcement facility. Police stations maintain statutory custody protocols "
            "for found property, especially valuable items, wallets, official IDs, and electronics.",
            RecommendationTier.PRIMARY,
            "Official statutory authority with dedicated property intake records.",
        )

    if category == HandoverCategory.CAMPUS_SECURITY:
        return (
            AcceptanceStatus.LIKELY,
            "Official campus security command desk. Serves as the designated lost-and-found intake "
            "depot for campus grounds, lecture buildings, and student residences.",
            RecommendationTier.PRIMARY,
            "Designated campus institutional repository for student and faculty property.",
        )

    if category == HandoverCategory.LOST_PROPERTY:
        return (
            AcceptanceStatus.LIKELY,
            "Specialized lost-and-found intake desk. Accepts and catalog-logs lost personal items.",
            RecommendationTier.PRIMARY,
            "Dedicated lost-and-found public service office.",
        )

    if category == HandoverCategory.TRANSIT:
        return (
            AcceptanceStatus.REQUIRES_STAFF_INQUIRY,
            "Staffed public transit station. Many stations operate passenger lost-property counters; "
            "please speak with the customer service or station master desk to confirm whether they accept items found nearby.",
            RecommendationTier.SECONDARY,
            "Major staffed transportation hub with passenger assistance desk.",
        )

    if category == HandoverCategory.PUBLIC_SERVICE:
        return (
            AcceptanceStatus.REQUIRES_STAFF_INQUIRY,
            "Civic or municipal administration building. Acceptance policies vary by department; "
            "please inquire with the main civic information desk before handing over items.",
            RecommendationTier.SECONDARY,
            "Staffed civic administrative office with public reception.",
        )

    if category == HandoverCategory.POST_OFFICE:
        return (
            AcceptanceStatus.REQUIRES_STAFF_INQUIRY,
            "CAVEAT: Ordinary post offices do NOT automatically accept found personal belongings. "
            "You must inquire directly with counter staff before handing over any property. "
            "Never leave unattended items at a postal counter.",
            RecommendationTier.CONDITIONAL,
            "Public postal counter — requires explicit on-site inquiry and staff agreement.",
        )

    return (
        AcceptanceStatus.UNCONFIRMED,
        "Publicly accessible facility. Contact staff at the reception counter to confirm handover acceptance.",
        RecommendationTier.CONDITIONAL,
        "Public facility without confirmed statutory lost property intake.",
    )


def compute_location_score(
    tier: RecommendationTier,
    category: HandoverCategory,
    travel_context: TravelContext,
    distance_km: float,
    has_phone: bool,
    has_hours: bool,
) -> float:
    """Compute transparent, multi-factor recommendation score."""
    # 1. Base score by tier
    if tier == RecommendationTier.PRIMARY:
        base = 70.0
    elif tier == RecommendationTier.SECONDARY:
        base = 45.0
    else:
        base = 25.0

    # 2. Travel context alignment boost
    context_boost = 0.0
    if travel_context == TravelContext.TRAIN_TRAVEL and category == HandoverCategory.TRANSIT:
        context_boost = 20.0
    elif travel_context == TravelContext.AIRPORT_TRAVEL and category == HandoverCategory.TRANSIT:
        context_boost = 20.0
    elif travel_context == TravelContext.CAMPUS and category == HandoverCategory.CAMPUS_SECURITY:
        context_boost = 25.0
    elif travel_context == TravelContext.WALKING_CITY and category == HandoverCategory.POLICE:
        context_boost = 15.0
    elif travel_context == TravelContext.ROAD_TRAVEL and category in (HandoverCategory.POLICE, HandoverCategory.TRANSIT):
        context_boost = 10.0

    # 3. Proximity score (decay with distance)
    # 0 km yields 30 pts, decaying gracefully
    proximity = max(0.0, 30.0 - (distance_km * 2.5))

    # 4. Verified contact/hours bonus (evidence-based)
    verified_bonus = 0.0
    if has_phone:
        verified_bonus += 5.0
    if has_hours:
        verified_bonus += 5.0

    total = base + context_boost + proximity + verified_bonus
    return round(total, 2)


def extract_address_components(raw_item: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """Extract clean street address and city from Nominatim address object."""
    addr = raw_item.get("address") or {}
    disp = raw_item.get("display_name") or ""

    city = (
        addr.get("city")
        or addr.get("town")
        or addr.get("village")
        or addr.get("municipality")
        or addr.get("county")
    )

    # Build concise street line
    parts = []
    road = addr.get("road") or addr.get("pedestrian") or addr.get("footway")
    suburb = addr.get("suburb") or addr.get("neighbourhood")
    postcode = addr.get("postcode")

    if road:
        parts.append(road)
    if suburb:
        parts.append(suburb)
    if city and city not in parts:
        parts.append(city)
    if postcode:
        parts.append(postcode)

    if parts:
        formatted_address = ", ".join(parts)
    else:
        # Fall back to first 3 elements of display_name
        formatted_address = ", ".join(disp.split(", ")[:3]) if disp else "Address details available on map"

    return formatted_address, city


def get_campus_location(user_lat: float, user_lon: float, travel_context: TravelContext) -> HandoverLocation:
    """Build the official campus security handover location."""
    dist_km = haversine_distance_km(user_lat, user_lon, config.CAMPUS_LATITUDE, config.CAMPUS_LONGITUDE)
    status, note, tier, reason = evaluate_acceptance(HandoverCategory.CAMPUS_SECURITY, config.CAMPUS_NAME)

    score = compute_location_score(
        tier=tier,
        category=HandoverCategory.CAMPUS_SECURITY,
        travel_context=travel_context,
        distance_km=dist_km,
        has_phone=bool(config.CAMPUS_PHONE),
        has_hours=bool(config.CAMPUS_HOURS),
    )

    return HandoverLocation(
        id="campus-security-primary",
        name=config.CAMPUS_NAME,
        category=HandoverCategory.CAMPUS_SECURITY,
        category_label="Campus Security Desk",
        latitude=config.CAMPUS_LATITUDE,
        longitude=config.CAMPUS_LONGITUDE,
        address=config.CAMPUS_ADDRESS,
        city=config.CAMPUS_CITY,
        distance_km=dist_km,
        distance_label=f"~{dist_km:.2f} km (straight-line)",
        phone=config.CAMPUS_PHONE,
        operating_hours=config.CAMPUS_HOURS,
        acceptance_status=status,
        acceptance_note=note,
        recommendation_tier=tier,
        recommendation_reason=reason,
        score=score,
        source="Campus Administrative Registry",
        directions_url_google=generate_google_directions_url(user_lat, user_lon, config.CAMPUS_LATITUDE, config.CAMPUS_LONGITUDE),
        directions_url_osm=generate_osm_directions_url(user_lat, user_lon, config.CAMPUS_LATITUDE, config.CAMPUS_LONGITUDE),
    )


class SafeHandoverService:
    """Coordinates provider lookups, category parsing, ranking, and deduplication."""

    def __init__(self, provider: Optional[BaseLocationProvider] = None):
        self.provider = provider or default_provider

    async def search_nearby_handovers(self, req: HandoverSearchRequest) -> HandoverSearchResponse:
        """Find, rank, and format safe handover locations near the given coordinates."""
        user_lat = req.latitude
        user_lon = req.longitude
        radius = req.radius_km
        cat_filter = (req.category or "all").lower()
        
        # Parse travel context safely
        try:
            travel_context = TravelContext(req.travel_context)
        except (ValueError, TypeError):
            travel_context = TravelContext.GENERAL

        # 1. Reverse-geocode user location if possible for context header
        user_address = await self.provider.reverse_geocode(user_lat, user_lon)

        # 2. Fetch raw nearby facilities from provider
        raw_items = await self.provider.search_nearby(
            lat=user_lat,
            lon=user_lon,
            radius_km=radius,
            category=cat_filter,
            limit=req.limit * 2,  # fetch broader candidate pool before ranking
        )

        locations: List[HandoverLocation] = []

        # 3. Consider Campus Security inclusion
        # Include campus if within max(radius, campus_radius) or if travel_context is campus
        campus_dist = haversine_distance_km(user_lat, user_lon, config.CAMPUS_LATITUDE, config.CAMPUS_LONGITUDE)
        campus_eligible = (
            campus_dist <= max(radius, config.CAMPUS_RADIUS_KM)
            or travel_context == TravelContext.CAMPUS
        )
        if campus_eligible and (cat_filter in ("all", "campus_security")):
            campus_loc = get_campus_location(user_lat, user_lon, travel_context)
            # Only include if within search radius or explicit campus mode
            if campus_dist <= radius or travel_context == TravelContext.CAMPUS:
                locations.append(campus_loc)

        # 4. Process provider items
        for item in raw_items:
            try:
                lat = float(item["lat"])
                lon = float(item["lon"])
            except (KeyError, ValueError, TypeError):
                continue

            dist_km = haversine_distance_km(user_lat, user_lon, lat, lon)
            if dist_km > radius:
                # Beyond straight-line radius
                continue

            name = item.get("name") or (item.get("display_name", "").split(",")[0] if item.get("display_name") else "Public Facility")
            category = classify_category(item)

            # Apply category filter if specific
            if cat_filter != "all" and category.value != cat_filter:
                continue

            extratags = item.get("extratags") or {}
            phone = extratags.get("phone") or extratags.get("contact:phone")
            hours = extratags.get("opening_hours") or extratags.get("service_times")

            status, note, tier, reason = evaluate_acceptance(category, name, extratags)
            score = compute_location_score(
                tier=tier,
                category=category,
                travel_context=travel_context,
                distance_km=dist_km,
                has_phone=bool(phone),
                has_hours=bool(hours),
            )

            addr_str, city_str = extract_address_components(item)
            osm_id = str(item.get("osm_id") or item.get("place_id") or f"{lat}_{lon}")

            category_labels = {
                HandoverCategory.POLICE: "Police Station",
                HandoverCategory.CAMPUS_SECURITY: "Campus Security Desk",
                HandoverCategory.LOST_PROPERTY: "Lost Property Office",
                HandoverCategory.TRANSIT: "Transit Customer Desk",
                HandoverCategory.PUBLIC_SERVICE: "Civic / Municipal Desk",
                HandoverCategory.POST_OFFICE: "Post Office",
            }

            loc = HandoverLocation(
                id=f"osm-{osm_id}",
                name=name,
                category=category,
                category_label=category_labels.get(category, "Public Handover Point"),
                latitude=lat,
                longitude=lon,
                address=addr_str,
                city=city_str,
                distance_km=dist_km,
                distance_label=f"~{dist_km:.2f} km (straight-line)",
                phone=phone,
                operating_hours=hours,
                acceptance_status=status,
                acceptance_note=note,
                recommendation_tier=tier,
                recommendation_reason=reason,
                score=score,
                source="OpenStreetMap",
                directions_url_google=generate_google_directions_url(user_lat, user_lon, lat, lon),
                directions_url_osm=generate_osm_directions_url(user_lat, user_lon, lat, lon),
            )
            locations.append(loc)

        # 5. Deduplicate locations within close proximity (<= 50 meters or same name within 80m)
        deduped = self._deduplicate_locations(locations)

        # 6. Sort by computed score descending, then distance ascending
        deduped.sort(key=lambda x: (-x.score, x.distance_km, x.name))

        # 7. Apply limit
        final_list = deduped[: req.limit]

        return HandoverSearchResponse(
            query_latitude=user_lat,
            query_longitude=user_lon,
            query_address=user_address,
            search_radius_km=radius,
            travel_context=travel_context.value,
            total_found=len(final_list),
            locations=final_list,
            safety_disclaimer=SAFETY_DISCLAIMER,
        )

    def _deduplicate_locations(self, locations: List[HandoverLocation]) -> List[HandoverLocation]:
        """Eliminate redundant duplicate records within 50-80 meters."""
        kept: List[HandoverLocation] = []
        for cand in locations:
            is_dup = False
            for existing in kept:
                sep = haversine_distance_km(cand.latitude, cand.longitude, existing.latitude, existing.longitude)
                clean_cand_name = re.sub(r"[^\w\s]", "", cand.name.lower()).strip()
                clean_exist_name = re.sub(r"[^\w\s]", "", existing.name.lower()).strip()

                same_name = (clean_cand_name == clean_exist_name) or (clean_cand_name in clean_exist_name) or (clean_exist_name in clean_cand_name)

                if (sep < 0.05) or (sep < 0.08 and same_name):
                    is_dup = True
                    # If candidate has richer metadata (phone or hours), upgrade existing record
                    if (not existing.phone and cand.phone) or (not existing.operating_hours and cand.operating_hours):
                        if cand.phone:
                            existing.phone = cand.phone
                        if cand.operating_hours:
                            existing.operating_hours = cand.operating_hours
                    break
            if not is_dup:
                kept.append(cand)
        return kept


# Default singleton service
default_service = SafeHandoverService()
