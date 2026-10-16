"""Service layer orchestrating attribute persistence, caching, multi-modal matching, and search."""

import logging
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.image_embeddings import encode_image
from app.ai.ranking import location_similarity, time_similarity
from app.ai.similarity import cosine_similarity, normalized_similarity
from app.ai.text_embeddings import encode_text
from app.db.models import ItemImage, ItemReport
from app.extensions.attribute_matching.extractor import (
    extract_attributes_from_image,
    extract_attributes_from_text,
    merge_attributes,
)
from app.extensions.attribute_matching.matcher import (
    calculate_composite_match_score,
    compare_attributes,
    compute_category_compatibility,
    resolve_canonical_object_type,
)
from app.extensions.attribute_matching.models import ItemAttributeRecord
from app.extensions.attribute_matching.schemas import (
    AttributeFilterRequest,
    AttributeMatchItem,
    AttributeSearchResponse,
    ItemAttributes,
    MatchExplanation,
)
from app.services.matching_service import get_or_create_report_image_vectors

logger = logging.getLogger(__name__)


def calibrate_clip_visual_similarity(cos_sim: float) -> float:
    """
    Calibrate raw CLIP cosine similarity into an honest visual match percentage [0, 100].

    Raw CLIP embeddings of physical objects in typical environments exhibit an ambient
    noise floor around cos ~ 0.55 - 0.65 due to table surfaces, lighting, and generic shapes.

    Calibration intervals:
    - cos <= 0.55: 0.0%
    - 0.55 < cos <= 0.65: 0.0% - 15.0% (ambient noise floor)
    - 0.65 < cos <= 0.78: 15.0% - 42.0% (superficial / cross-object similarity)
    - 0.78 < cos <= 0.88: 42.0% - 75.0% (moderately strong visual similarity)
    - cos > 0.88: 75.0% - 100.0% (genuine visual identity / identical item)
    """
    if cos_sim <= 0.55:
        return 0.0
    elif cos_sim <= 0.65:
        return round(((cos_sim - 0.55) / 0.10) * 15.0, 2)
    elif cos_sim <= 0.78:
        return round(15.0 + ((cos_sim - 0.65) / 0.13) * 27.0, 2)
    elif cos_sim <= 0.88:
        return round(42.0 + ((cos_sim - 0.78) / 0.10) * 33.0, 2)
    else:
        ratio = min(1.0, (cos_sim - 0.88) / 0.12)
        return round(75.0 + ratio * 25.0, 2)



def get_or_create_attributes(db: Session, report: ItemReport) -> ItemAttributes:
    """
    Retrieve cached ItemAttributes from database or extract, persist, and return them.
    Prevents repeated expensive visual or text inference.
    """
    record = db.scalar(
        select(ItemAttributeRecord).where(ItemAttributeRecord.report_id == report.id)
    )

    if record is not None:
        patterns = record.patterns if isinstance(record.patterns, list) else ([record.patterns] if record.patterns else [])
        distinctive_features = (
            record.distinctive_features
            if isinstance(record.distinctive_features, list)
            else ([record.distinctive_features] if record.distinctive_features else [])
        )
        conf_scores = record.confidence_scores if isinstance(record.confidence_scores, dict) else {}

        return ItemAttributes(
            category=record.category,
            primary_color=record.primary_color,
            secondary_color=record.secondary_color,
            is_multicolor=record.is_multicolor,
            shape=record.shape,
            size_category=record.size_category,
            dimensions_text=record.dimensions_text,
            capacity_litres=record.capacity_litres,
            capacity_text=record.capacity_text,
            material=record.material,
            patterns=patterns,
            distinctive_features=distinctive_features,
            confidence_scores=conf_scores,
        )

    # 1. Extract from report textual metadata
    text_attrs = extract_attributes_from_text(
        title=report.item_name,
        description=report.description,
        category=report.category,
        color=report.color,
    )

    # 2. Extract from primary image if available
    image_attrs: Optional[ItemAttributes] = None
    if report.images:
        primary_image = report.images[0]
        try:
            image_attrs = extract_attributes_from_image(primary_image.image_path)
        except Exception as exc:
            logger.debug(f"Could not extract vision attributes for report {report.id}: {exc}")

    # 3. Merge attributes
    final_attrs = merge_attributes(text_attrs, image_attrs)

    # 4. Persist to database
    new_record = ItemAttributeRecord(
        report_id=report.id,
        category=final_attrs.category,
        primary_color=final_attrs.primary_color,
        secondary_color=final_attrs.secondary_color,
        is_multicolor=final_attrs.is_multicolor,
        shape=final_attrs.shape,
        size_category=final_attrs.size_category,
        dimensions_text=final_attrs.dimensions_text,
        capacity_litres=final_attrs.capacity_litres,
        capacity_text=final_attrs.capacity_text,
        material=final_attrs.material,
        patterns=final_attrs.patterns,
        distinctive_features=final_attrs.distinctive_features,
        confidence_scores=final_attrs.confidence_scores,
        raw_attributes=final_attrs.model_dump(),
    )
    db.add(new_record)
    try:
        db.commit()
        db.refresh(new_record)
    except Exception:
        db.rollback()

    return final_attrs


def search_by_attributes(
    db: Session,
    request: AttributeFilterRequest,
    query_image_bytes_list: Optional[List[bytes]] = None,
) -> AttributeSearchResponse:
    """
    Search and rank candidate reports using attribute filters, natural language, and optional query photos.
    Does NOT create any report records. Distinguishes hard filters from soft ranking preferences.
    """
    query_image_bytes_list = query_image_bytes_list or []

    # 1. Formulate Query Attributes
    query_text = request.query_text or ""
    query_text_attrs = extract_attributes_from_text(
        title="",
        description=query_text,
        category=request.category,
        color=request.primary_color,
    )

    # Incorporate query image visual attributes
    query_image_attrs: Optional[ItemAttributes] = None
    query_image_vectors: List[List[float]] = []

    for img_bytes in query_image_bytes_list:
        try:
            vec = encode_image(img_bytes)
            query_image_vectors.append(vec)
            if query_image_attrs is None:
                query_image_attrs = extract_attributes_from_image(img_bytes)
        except Exception as exc:
            logger.warning(f"Error encoding query image: {exc}")

    merged_query_attrs = merge_attributes(query_text_attrs, query_image_attrs)

    # Explicit form parameters override unstated query attributes
    if request.category:
        merged_query_attrs.category = request.category
    if request.primary_color:
        merged_query_attrs.primary_color = request.primary_color
    if request.secondary_color:
        merged_query_attrs.secondary_color = request.secondary_color
    if request.shape:
        merged_query_attrs.shape = request.shape
    if request.size_category:
        merged_query_attrs.size_category = request.size_category
    if request.material:
        merged_query_attrs.material = request.material
    if request.distinctive_features:
        features_to_add = [f.strip().capitalize() for f in request.distinctive_features.split(",") if f.strip()]
        merged_query_attrs.distinctive_features.extend(features_to_add)

    user_specified_category = bool(request.category and request.category.strip())
    user_specified_text = bool(query_text and query_text.strip())

    # Resolve Query Canonical Type
    if user_specified_category or user_specified_text:
        query_canonical_type = resolve_canonical_object_type(
            category=merged_query_attrs.category if user_specified_category else None,
            item_name="",
            description=query_text,
        )
    elif query_image_attrs and query_image_attrs.confidence_scores.get("category", 0.0) >= 0.75:
        query_canonical_type = resolve_canonical_object_type(
            category=query_image_attrs.category,
            item_name="",
            description="",
        )
    else:
        query_canonical_type = "unknown"

    # 2. Retrieve Candidate Reports
    statement = select(ItemReport).where(ItemReport.status == "active")
    if request.target_type:
        statement = statement.where(ItemReport.report_type == request.target_type.lower())

    candidates = db.scalars(statement).all()

    # Pre-encode query text vector if text is provided
    query_text_vec = None
    if query_text.strip():
        try:
            query_text_vec = encode_text(query_text)
        except Exception:
            pass

    hard_filter_set = set(k.lower() for k in request.hard_filters)
    ranked_items: List[AttributeMatchItem] = []

    for candidate in candidates:
        cand_attrs = get_or_create_attributes(db, candidate)

        # Resolve Candidate Canonical Type using category, item_name, description
        cand_canonical_type = resolve_canonical_object_type(
            category=cand_attrs.category,
            item_name=candidate.item_name,
            description=candidate.description,
        )

        cat_compat, cat_tier, cat_reason = compute_category_compatibility(
            type_a=query_canonical_type,
            type_b=cand_canonical_type,
            raw_cat_a=merged_query_attrs.category,
            raw_cat_b=cand_attrs.category,
        )

        # Enforce Hard Filters
        if "category" in hard_filter_set and (merged_query_attrs.category or query_canonical_type != "unknown"):
            # Require at least related compatibility (cat_compat >= 0.50). Incompatible items (< 0.50) are excluded.
            if cat_compat < 0.50:
                continue

        if "primary_color" in hard_filter_set and merged_query_attrs.primary_color:
            if not cand_attrs.primary_color or cand_attrs.primary_color.lower() != merged_query_attrs.primary_color.lower():
                continue

        if "shape" in hard_filter_set and merged_query_attrs.shape:
            if not cand_attrs.shape or cand_attrs.shape.lower() != merged_query_attrs.shape.lower():
                continue

        if "size_category" in hard_filter_set and merged_query_attrs.size_category:
            if not cand_attrs.size_category or cand_attrs.size_category.lower() != merged_query_attrs.size_category.lower():
                continue

        if "material" in hard_filter_set and merged_query_attrs.material:
            if not cand_attrs.material or cand_attrs.material.lower() != merged_query_attrs.material.lower():
                continue

        # Compare Attributes with contextual canonical types
        attr_score, attr_meta, explanation = compare_attributes(
            attrs1=merged_query_attrs,
            attrs2=cand_attrs,
            canonical_type1=query_canonical_type,
            canonical_type2=cand_canonical_type,
        )

        # Visual Score (from query photos if present)
        visual_score = None
        cand_image_pairs = get_or_create_report_image_vectors(db, candidate)
        best_cand_image_path = None
        if cand_image_pairs:
            best_cand_image_path = cand_image_pairs[0][0].image_path

        if query_image_vectors and cand_image_pairs:
            cand_vectors = [vec for _, vec in cand_image_pairs]
            sim_matrix = [
                [cosine_similarity(q, c) for c in cand_vectors]
                for q in query_image_vectors
            ]
            max_sim = max(max(row) for row in sim_matrix)
            query_best_matches = [max(row) for row in sim_matrix]
            coverage_sim = sum(query_best_matches) / len(query_best_matches)
            raw_visual_sim = (0.80 * max_sim) + (0.20 * coverage_sim)
            visual_score = calibrate_clip_visual_similarity(raw_visual_sim)

            # Only generate visual appearance reason if genuine visual match (>= 65%) and category is at least related
            if visual_score >= 65.0 and cat_compat >= 0.30:
                explanation.reasons.insert(0, f"Similar overall appearance ({visual_score:.0f}% visual match)")

        # Text Score (from query text if present)
        text_score = None
        if query_text_vec is not None:
            from app.services.matching_service import get_or_create_text_embedding
            cand_text_vec = get_or_create_text_embedding(db, candidate)
            raw_text_cos = cosine_similarity(query_text_vec, cand_text_vec)
            text_score = round(max(0.0, raw_text_cos) * 100, 2)

        has_distinctive = len(explanation.shared_distinctive_features) > 0

        # Calculate final composite match score with category gating
        composite_score = calculate_composite_match_score(
            visual_score=visual_score,
            text_score=text_score,
            attribute_score=attr_score,
            has_distinctive_match=has_distinctive,
            category_compatibility=cat_compat,
        )

        # Quality cutoff: do not include items if match score is less than min_score (default 30.0%)
        # or if the item belongs to an incompatible category when query type is known
        if composite_score < request.min_score:
            continue
        if request.min_score >= 10.0 and query_canonical_type != "unknown" and cat_compat <= 0.05:
            continue

        best_image_url = (
            f"/{best_cand_image_path}"
            if best_cand_image_path and not best_cand_image_path.startswith("/")
            else best_cand_image_path
        )

        event_date_str = candidate.event_date.isoformat() if candidate.event_date else None

        ranked_items.append(
            AttributeMatchItem(
                report_id=candidate.id,
                item_name=candidate.item_name,
                category=candidate.category,
                report_type=candidate.report_type,
                location_text=candidate.location_text,
                event_date=event_date_str,
                description=candidate.description,
                color=candidate.color,
                brand=candidate.brand,
                model=candidate.model,
                match_score=composite_score,
                visual_score=visual_score,
                text_score=text_score,
                attribute_score=attr_score,
                attributes=cand_attrs,
                explanation=explanation,
                best_image_url=best_image_url,
                candidate_image_count=len(cand_image_pairs),
            )
        )

    # Sort descending by match_score, breaking ties by report_id
    ranked_items.sort(key=lambda item: (item.match_score, item.report_id), reverse=True)

    return AttributeSearchResponse(
        query_attributes=merged_query_attrs,
        query_image_count=len(query_image_bytes_list),
        candidate_count=len(ranked_items),
        matches=ranked_items[:request.limit],
    )
