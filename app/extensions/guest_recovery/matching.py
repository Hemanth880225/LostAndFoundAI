"""Journey and Time-Aware Matching Engine for Transit and Guest Recovery.

Extends the core CLIP and attribute matching pipeline to evaluate:
- Journey type compatibility (e.g. auto-rickshaw, taxi, train).
- Route overlap (pickup and drop-off areas).
- Approximate time-of-day alignment.
- Visual and textual CLIP embeddings.
Treats unknown metadata as neutral (unknown), ensuring missing GPS or missing route details
never penalize candidates.
"""

import re
from datetime import date
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.ranking import attribute_similarity, location_similarity, time_similarity
from app.ai.similarity import normalized_similarity
from app.db.models import GuestRecoveryReport, ItemReport
from app.services.matching_service import (
    get_or_create_image_embeddings,
    get_or_create_text_embedding,
)


TRANSIT_COMPATIBILITY_GROUPS = [
    {"auto_rickshaw", "taxi", "cab"},
    {"train", "metro", "railway", "local_train"},
    {"bus", "city_bus", "shuttle"},
    {"walking", "pedestrian"},
    {"flight", "airport"},
]


def _journey_type_similarity(type1: Optional[str], type2: Optional[str]) -> Optional[float]:
    """Compare two journey types. Returns None if either is unknown."""
    if not type1 or not type2:
        return None

    t1 = type1.strip().lower()
    t2 = type2.strip().lower()

    if t1 == t2:
        return 1.0

    # Check transit group compatibility
    for group in TRANSIT_COMPATIBILITY_GROUPS:
        if t1 in group and t2 in group:
            return 0.75

    return 0.25


def _extract_keywords(text: Optional[str]) -> set[str]:
    """Extract significant lowercase word tokens from location and route strings."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    stop_words = {"to", "from", "near", "at", "in", "the", "and", "via", "road", "street", "stand", "complex"}
    return {word for word in cleaned.split() if len(word) >= 3 and word not in stop_words}


def _route_overlap_similarity(
    rep1: ItemReport,
    meta1: Optional[GuestRecoveryReport],
    rep2: ItemReport,
    meta2: Optional[GuestRecoveryReport],
) -> Optional[float]:
    """Calculate route overlap using pickup, dropoff, route notes, and location text."""
    tokens1 = _extract_keywords(rep1.location_text)
    tokens2 = _extract_keywords(rep2.location_text)

    if meta1:
        tokens1 |= _extract_keywords(meta1.pickup_location)
        tokens1 |= _extract_keywords(meta1.dropoff_location)
        tokens1 |= _extract_keywords(meta1.route_notes)

    if meta2:
        tokens2 |= _extract_keywords(meta2.pickup_location)
        tokens2 |= _extract_keywords(meta2.dropoff_location)
        tokens2 |= _extract_keywords(meta2.route_notes)

    if not tokens1 or not tokens2:
        return None

    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)

    if not union:
        return None

    # Jaccard overlap with floor for partial matches
    jaccard = len(intersection) / len(union)
    if intersection:
        return min(1.0, 0.4 + jaccard * 1.5)
    return 0.10


def _time_window_similarity(time1: Optional[str], time2: Optional[str]) -> Optional[float]:
    """Evaluate approximate time-of-day alignment (e.g. 'Morning', '10:30 AM')."""
    if not time1 or not time2:
        return None

    t1 = time1.strip().lower()
    t2 = time2.strip().lower()

    if t1 == t2:
        return 1.0

    windows = {
        "morning": {"morning", "am", "early", "dawn", "06", "07", "08", "09", "10", "11"},
        "afternoon": {"afternoon", "pm", "noon", "midday", "12", "13", "14", "15", "16"},
        "evening": {"evening", "dusk", "17", "18", "19", "20"},
        "night": {"night", "late", "midnight", "21", "22", "23", "00", "01", "02"},
    }

    w1 = set()
    w2 = set()
    for win_name, kws in windows.items():
        if any(kw in t1 for kw in kws):
            w1.add(win_name)
        if any(kw in t2 for kw in kws):
            w2.add(win_name)

    if not w1 or not w2:
        return None

    if w1.intersection(w2):
        return 0.90

    # Adjacent windows
    adj = {
        ("morning", "afternoon"), ("afternoon", "evening"),
        ("evening", "night"), ("night", "morning")
    }
    for a in w1:
        for b in w2:
            if (a, b) in adj or (b, a) in adj:
                return 0.50

    return 0.20


def score_guest_candidate(
    db: Session,
    report: ItemReport,
    candidate: ItemReport,
    meta_report: Optional[GuestRecoveryReport],
    meta_cand: Optional[GuestRecoveryReport],
) -> Dict[str, Any]:
    """Score a candidate considering CLIP text/image, attributes, journey, route, and time."""
    # 1. Base text score
    text1 = get_or_create_text_embedding(db, report)
    text2 = get_or_create_text_embedding(db, candidate)
    text_score = normalized_similarity(text1, text2)

    # 2. Base image score (if images exist on both)
    imgs1 = get_or_create_image_embeddings(db, report)
    imgs2 = get_or_create_image_embeddings(db, candidate)
    image_score = None
    if imgs1 and imgs2:
        image_score = max(
            normalized_similarity(v1, v2)
            for v1 in imgs1
            for v2 in imgs2
        )

    # 3. Attributes, location, and date
    attr_score = attribute_similarity(report, candidate)
    loc_score = location_similarity(report, candidate)
    date_score = time_similarity(report.event_date, candidate.event_date)

    # 4. Transit & Journey components
    journey_type1 = meta_report.journey_type if meta_report else None
    journey_type2 = meta_cand.journey_type if meta_cand else None
    journey_score = _journey_type_similarity(journey_type1, journey_type2)

    route_score = _route_overlap_similarity(report, meta_report, candidate, meta_cand)

    approx_time1 = meta_report.approximate_time if meta_report else None
    approx_time2 = meta_cand.approximate_time if meta_cand else None
    time_window_score = _time_window_similarity(approx_time1, approx_time2)

    # Weights configuration
    weights = {
        "text": 0.25,
        "image": 0.25,
        "attributes": 0.15,
        "location": 0.10,
        "date": 0.05,
        "journey": 0.10,
        "route": 0.05,
        "time_window": 0.05,
    }

    components = {
        "text": text_score,
        "attributes": attr_score,
    }

    if image_score is not None:
        components["image"] = image_score
    if loc_score is not None:
        components["location"] = loc_score
    if date_score is not None:
        components["date"] = date_score
    if journey_score is not None:
        components["journey"] = journey_score
    if route_score is not None:
        components["route"] = route_score
    if time_window_score is not None:
        components["time_window"] = time_window_score

    # Normalize across available components only
    total_weight = sum(weights[k] for k in components)
    final_score = sum(weights[k] * val for k, val in components.items()) / total_weight

    # Formulate human-readable explanation
    explanation_parts = []
    if text_score > 0.65:
        explanation_parts.append("High item description similarity")
    if image_score is not None and image_score > 0.65:
        explanation_parts.append("Strong visual resemblance")
    if journey_score is not None and journey_score >= 0.75:
        j_label = (journey_type1 or journey_type2 or "transit").replace("_", " ")
        explanation_parts.append(f"Matching {j_label} journey context")
    if route_score is not None and route_score >= 0.40:
        explanation_parts.append("Corroborating pickup/dropoff route overlap")
    if not explanation_parts:
        explanation_parts.append("Potential match based on shared category and attributes")

    return {
        "score": round(final_score * 100, 2),
        "components": {k: round(v, 4) for k, v in components.items()},
        "explanation": "; ".join(explanation_parts),
        "journey_context": {
            "query_journey": journey_type1,
            "candidate_journey": journey_type2,
            "journey_compatible": journey_score is not None and journey_score >= 0.70,
        },
    }


def find_guest_matches(
    db: Session,
    report_id: int,
    limit: int = 10,
    min_score: float = 35.0,
) -> List[Dict[str, Any]]:
    """Retrieve and rank plausible match candidates for a guest or standard report."""
    query_report = db.get(ItemReport, report_id)
    if not query_report or query_report.status != "active":
        return []

    target_type = "lost" if query_report.report_type == "found" else "found"

    # Fetch candidate reports from database
    candidates = db.scalars(
        select(ItemReport)
        .where(
            ItemReport.report_type == target_type,
            ItemReport.status == "active",
            ItemReport.id != report_id,
        )
    ).all()

    if not candidates:
        return []

    # Pre-fetch metadata
    meta_report = db.scalars(
        select(GuestRecoveryReport).where(GuestRecoveryReport.report_id == query_report.id)
    ).first()

    candidate_ids = [c.id for c in candidates]
    cand_metas = {
        m.report_id: m
        for m in db.scalars(
            select(GuestRecoveryReport).where(GuestRecoveryReport.report_id.in_(candidate_ids))
        ).all()
    }

    scored_candidates = []
    for cand in candidates:
        try:
            score_data = score_guest_candidate(
                db=db,
                report=query_report,
                candidate=cand,
                meta_report=meta_report,
                meta_cand=cand_metas.get(cand.id),
            )
            if score_data["score"] >= min_score:
                scored_candidates.append({
                    "candidate_report_id": cand.id,
                    "item_name": cand.item_name,
                    "category": cand.category,
                    "location_text": cand.location_text,
                    "event_date": cand.event_date.isoformat(),
                    "score": score_data["score"],
                    "components": score_data["components"],
                    "explanation": score_data["explanation"],
                    "journey_context": score_data["journey_context"],
                })
        except Exception:
            # Resilient fallback if candidate has malformed vector or text
            continue

    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    return scored_candidates[:limit]
