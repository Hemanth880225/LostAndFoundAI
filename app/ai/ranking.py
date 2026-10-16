import math
import unicodedata
from datetime import date
from difflib import SequenceMatcher

from app.db.models import ItemReport


def normalize_text(value: str | None) -> str:
    """Normalize text while preserving Unicode letters and marks."""

    if not isinstance(value, str) or not value.strip():
        return ""

    value = value.casefold()
    tokens = []
    current_token = []

    for character in value:
        category = unicodedata.category(character)

        # Preserve letters, numbers, and combining marks.
        if category.startswith(("L", "N")) or (
            category.startswith("M") and current_token
        ):
            current_token.append(character)

        elif current_token:
            tokens.append("".join(current_token))
            current_token = []

    if current_token:
        tokens.append("".join(current_token))

    return " ".join(tokens)


def text_similarity(
    a: str | None,
    b: str | None,
) -> float:
    """Calculate lexical similarity, not semantic similarity."""

    a = normalize_text(a)
    b = normalize_text(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def attribute_similarity(
    lost: ItemReport,
    found: ItemReport,
) -> float:
    """Compare attributes available in both reports."""

    fields = ("category", "brand", "model", "color")
    scores = []

    for field in fields:
        left = normalize_text(getattr(lost, field, None))
        right = normalize_text(getattr(found, field, None))

        # Do not penalize a missing attribute as a mismatch.
        if not left or not right:
            continue

        if field == "category":
            scores.append(float(left == right))
        else:
            scores.append(text_similarity(left, right))

    return sum(scores) / len(scores) if scores else 0.0


def location_similarity(
    lost: ItemReport,
    found: ItemReport,
) -> float | None:
    """Calculate geographic proximity when coordinates are available."""

    coordinates = (
        lost.latitude,
        lost.longitude,
        found.latitude,
        found.longitude,
    )

    if any(value is None for value in coordinates):
        return None

    lat1, lon1, lat2, lon2 = map(math.radians, coordinates)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    haversine = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    # Guard against floating-point rounding at the boundaries.
    haversine = max(0.0, min(1.0, haversine))

    distance_km = 6371.0 * 2 * math.asin(
        math.sqrt(haversine)
    )

    # Nearby locations score higher than distant locations.
    return math.exp(-distance_km / 2.0)


def time_similarity(
    lost_date: date | None,
    found_date: date | None,
) -> float | None:
    """Calculate event-date proximity when dates are available."""

    if lost_date is None or found_date is None:
        return None

    gap_days = abs((found_date - lost_date).days)

    return math.exp(-gap_days / 7.0)


def rank_candidate(
    lost: ItemReport,
    found: ItemReport,
) -> dict:
    """Calculate a baseline score using text and metadata."""

    text_score = text_similarity(
        f"{lost.item_name} {lost.description}",
        f"{found.item_name} {found.description}",
    )

    attribute_score = attribute_similarity(lost, found)
    location_score = location_similarity(lost, found)
    time_score = time_similarity(
        lost.event_date,
        found.event_date,
    )

    weights = {
        "text": 0.30,
        "attributes": 0.15,
        "location": 0.12,
        "time": 0.08,
    }

    components = {
        "text": text_score,
        "attributes": attribute_score,
    }

    if location_score is not None:
        components["location"] = location_score

    if time_score is not None:
        components["time"] = time_score

    available_weight = sum(
        weights[key] for key in components
    )

    total = sum(
        weights[key] * value
        for key, value in components.items()
    ) / available_weight

    return {
        "score": round(total * 100, 2),
        "components": {
            key: round(value, 4)
            for key, value in components.items()
        },
    }
