
import math
import re
from datetime import date
from difflib import SequenceMatcher

from app.db.models import ItemReport


def normalize_text(value: str | None) -> str:
    """Normalize text for basic lexical comparison."""
    if not value:
        return ""

    return " ".join(
        re.findall(r"[a-z0-9]+", value.lower())
    )



def text_similarity(a: str, b: str) -> float:
    """
    Baseline lexical similarity.
    This is NOT semantic embedding similarity.
    """
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

        # Missing information should not count as a mismatch.
        if not left or not right:
            continue

        if field == "category":
            # Category is expected to agree.
            scores.append(float(left == right))
        else:
            scores.append(text_similarity(left, right))

    return sum(scores) / len(scores) if scores else 0.0


def location_similarity(
    lost: ItemReport,
    found: ItemReport,
) -> float:
    """Score proximity when both reports have coordinates."""
    coordinates = (
        lost.latitude,
        lost.longitude,
        found.latitude,
        found.longitude,
    )

    if any(value is None for value in coordinates):
        return 0.0

    lat1, lon1, lat2, lon2 = map(math.radians, coordinates)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    haversine = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    distance_km = 6371.0 * 2 * math.asin(
        min(1.0, math.sqrt(haversine))
    )

    # Full score at the same location; decays with distance.
    return math.exp(-distance_km / 2.0)


def time_similarity(
    lost_date: date,
    found_date: date,
) -> float:
    """Prefer reports with nearby event dates."""
    gap_days = abs((found_date - lost_date).days)

    # Full score on the same day, decaying over time.
    return math.exp(-gap_days / 7.0)


def rank_candidate(
    lost: ItemReport,
    found: ItemReport,
) -> dict:
    """
    Baseline ranking. Visual and semantic embeddings
    will be integrated in the next stage.
    """
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

    # The available signals are renormalized because
    # the image model has not been integrated yet.
    weights = {
        "text": 0.30,
        "attributes": 0.15,
        "location": 0.12,
        "time": 0.08,
    }

    available_weight = sum(weights.values())

    total = (
        weights["text"] * text_score
        + weights["attributes"] * attribute_score
        + weights["location"] * location_score
        + weights["time"] * time_score
    ) / available_weight

    return {
        "score": round(total * 100, 2),
        "components": {
            "text": round(text_score, 4),
            "attributes": round(attribute_score, 4),
            "location": round(location_score, 4),
            "time": round(time_score, 4),
        },
    }
