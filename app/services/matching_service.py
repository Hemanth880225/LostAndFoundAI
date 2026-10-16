
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.clip_model import MODEL_NAME
from app.ai.image_embeddings import encode_image
from app.ai.similarity import normalized_similarity
from app.ai.text_embeddings import encode_text
from app.ai.ranking import (
    attribute_similarity,
    location_similarity,
    time_similarity,
)
from app.ai.rule_engine import evaluate_match
from app.db.models import ItemEmbedding, ItemImage, ItemReport
from app.services.embedding_service import get_embedding, save_embedding

import logging

logger = logging.getLogger(__name__)




def report_text(report: ItemReport) -> str:
    """Build one searchable text description from a report."""

    values = (
        report.item_name,
        report.category,
        report.brand,
        report.model,
        report.color,
        report.description,
    )

    return " ".join(
        str(value).strip()
        for value in values
        if value and str(value).strip()
    )


def get_or_create_text_embedding(
    db: Session,
    report: ItemReport,
) -> list[float]:
    """Reuse a saved text embedding or generate and save a new one."""

    vector = get_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        model_name=MODEL_NAME,
    )

    if vector is not None:
        return vector

    text = report_text(report)

    if not text:
        raise ValueError(
            f"Report {report.id} has no text available for matching."
        )

    vector = encode_text(text)

    save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=vector,
        model_name=MODEL_NAME,
    )

    return vector



def get_or_create_report_image_vectors(
    db: Session,
    report: ItemReport,
) -> list[tuple[ItemImage, list[float]]]:
    """Retrieve or generate image embeddings paired with their ItemImage records."""

    images = db.scalars(
        select(ItemImage)
        .where(ItemImage.report_id == report.id)
        .order_by(ItemImage.id.asc())
    ).all()

    pairs: list[tuple[ItemImage, list[float]]] = []
    project_root = Path(__file__).resolve().parents[2]

    for image in images:
        stored = db.scalars(
            select(ItemEmbedding).where(
                ItemEmbedding.report_id == report.id,
                ItemEmbedding.image_id == image.id,
                ItemEmbedding.embedding_type == "image",
                ItemEmbedding.model_name == MODEL_NAME,
            )
        ).first()

        if stored is not None:
            pairs.append((image, stored.vector))
            continue

        image_path = Path(image.image_path)

        if not image_path.is_absolute():
            image_path = project_root / image_path

        try:
            vector = encode_image(image_path)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning(
                "Skipping unavailable or unreadable image %s "
                "for report %s: %s",
                image.id,
                report.id,
                exc,
            )
            continue

        save_embedding(
            db=db,
            report_id=report.id,
            image_id=image.id,
            embedding_type="image",
            vector=vector,
            model_name=MODEL_NAME,
        )

        pairs.append((image, vector))

    return pairs


def get_or_create_image_embeddings(
    db: Session,
    report: ItemReport,
) -> list[list[float]]:
    """Reuse valid stored image embeddings and generate missing ones."""

    pairs = get_or_create_report_image_vectors(db, report)
    return [vec for _, vec in pairs]






def score_candidate(
    db: Session,
    lost: ItemReport,
    found: ItemReport,
) -> dict:
    """Calculate text, image, attribute, location, and time similarity."""

    lost_text = get_or_create_text_embedding(db, lost)
    found_text = get_or_create_text_embedding(db, found)

    text_score = normalized_similarity(lost_text, found_text)

    lost_images = get_or_create_image_embeddings(db, lost)
    found_images = get_or_create_image_embeddings(db, found)

    image_score = None

    if lost_images and found_images:
        image_score = max(
            normalized_similarity(lost_vector, found_vector)
            for lost_vector in lost_images
            for found_vector in found_images
        )


    attribute_score = attribute_similarity(lost, found)
    location_score = location_similarity(lost, found)
    time_score = time_similarity(
        lost.event_date,
        found.event_date,
    )

    weights = {
        "text": 0.30,
        "image": 0.35,
        "attributes": 0.15,
        "location": 0.12,
        "time": 0.08,
    }

    components = {
        "text": text_score,
        "attributes": attribute_score,
    }

    if image_score is not None:
        components["image"] = image_score

    if location_score is not None:
        components["location"] = location_score

    if time_score is not None:
        components["time"] = time_score

    total_weight = sum(weights[key] for key in components)

    score = sum(
        weights[key] * value
        for key, value in components.items()
    ) / total_weight

    return {
        "score": round(score * 100, 2),
        "components": {
            key: round(value, 4)
            for key, value in components.items()
        },
    }






def find_matches(
    db: Session,
    report_id: int,
    limit: int = 10,
) -> dict:
    """Find, score, explain, and rank potential matching reports."""

    if limit < 1 or limit > 100:
        raise ValueError("Limit must be between 1 and 100.")

    report = db.get(ItemReport, report_id)

    if report is None:
        raise ValueError("Report not found.")

    if report.status != "active":
        raise ValueError("Only active reports can be matched.")

    if report.report_type not in {"lost", "found"}:
        raise ValueError("Report type must be lost or found.")

    opposite_type = "found" if report.report_type == "lost" else "lost"

    # Do not require an exact category match: similarity and rules
    # should also get a chance to evaluate differently categorized items.
    statement = select(ItemReport).where(
        ItemReport.report_type == opposite_type,
        ItemReport.status == "active",
        ItemReport.id != report.id,
    )

    candidates = db.scalars(statement).all()
    ranked = []

    for candidate in candidates:
        if report.report_type == "lost":
            lost, found = report, candidate
        else:
            lost, found = candidate, report

        # Step 1: calculate AI and metadata scores.
        result = score_candidate(db, lost, found)

        # Step 2: derive evidence and apply the rule engine.
        reasoning = evaluate_match(
            lost=lost,
            found=found,
            components=result["components"],
        )

        event_date = (
            candidate.event_date.isoformat()
            if candidate.event_date is not None
            else None
        )

        # Attribute recognition and explainability
        try:
            from app.extensions.attribute_matching.service import get_or_create_attributes
            from app.extensions.attribute_matching.matcher import compare_attributes
            lost_attrs = get_or_create_attributes(db, lost)
            found_attrs = get_or_create_attributes(db, found)
            _, _, explanation = compare_attributes(lost_attrs, found_attrs)
            candidate_attrs = found_attrs if report.report_type == "lost" else lost_attrs
            match_explanation = explanation.model_dump()
            attributes_data = candidate_attrs.model_dump()
        except Exception:
            match_explanation = None
            attributes_data = None

        ranked.append(
            {
                "report_id": candidate.id,
                "item_name": candidate.item_name,
                "category": candidate.category,
                "report_type": candidate.report_type,
                "location_text": candidate.location_text,
                "event_date": event_date,
                "match_score": result["score"],
                "score_components": result["components"],
                "reasoning": reasoning,
                "attributes": attributes_data,
                "match_explanation": match_explanation,
            }
        )

    # Rule-supported candidates rank first; similarity breaks ties.
    ranked.sort(
        key=lambda item: (
            item["reasoning"]["plausible_match"],
            item["match_score"],
        ),
        reverse=True,
    )

    return {
        "source_report_id": report.id,
        "candidate_count": len(ranked),
        "matches": ranked[:limit],
    }


def find_matches_by_image(
    db: Session,
    query_vectors: list[list[float]],
    target_type: str | None = None,
    limit: int = 10,
) -> dict:
    """
    Search and rank candidate reports using query image embedding vectors.

    AGGREGATION METHOD & EVIDENCE COMBINATION:
    Given M query image vectors Q = [q_1, ..., q_M] and K candidate report images
    C = [c_1, ..., c_K]:
    1. Pairwise Normalized Similarity:
       For every query vector q_m and candidate vector c_k, calculate normalized
       cosine similarity s(q_m, c_k) in [0, 1] using normalized_similarity().
    2. Best View Similarity (Max-pooling):
       S_max = max_{m, k} s(q_m, c_k)
       Measures the single strongest visual alignment between any query view and candidate photo.
    3. Multi-View Coverage (Mean of best matches per query image):
       S_coverage = (1 / M) * sum_{m=1}^M max_k s(q_m, c_k)
       Measures whether multiple query angles (e.g., front and back photos) find consistent support.
    4. Combined Visual Score:
       S = 0.80 * S_max + 0.20 * S_coverage
       Strictly bounded in [0, 1] (reported as match_score in [0, 100]).
       Reports with multiple photos do not gain an unfair additive advantage because candidate
       photos are aggregated via maximums rather than sums.
    5. Deduplication:
       Each candidate report appears strictly once in the ranked output.
    """
    if limit < 1 or limit > 100:
        raise ValueError("Limit must be between 1 and 100.")

    if not query_vectors:
        raise ValueError("At least one query image vector must be provided.")

    statement = select(ItemReport).where(ItemReport.status == "active")
    if target_type is not None:
        if target_type not in {"lost", "found"}:
            raise ValueError("Target report type must be 'lost' or 'found'.")
        statement = statement.where(ItemReport.report_type == target_type)

    candidates = db.scalars(statement).all()
    ranked = []

    for candidate in candidates:
        image_pairs = get_or_create_report_image_vectors(db, candidate)
        if not image_pairs:
            continue

        cand_images = [img for img, _ in image_pairs]
        cand_vectors = [vec for _, vec in image_pairs]

        # Calculate similarity matrix: shape (len(query_vectors), len(cand_vectors))
        sim_matrix = [
            [normalized_similarity(q, c) for c in cand_vectors]
            for q in query_vectors
        ]

        # 1. Best match across all query-candidate pairs
        max_sim = 0.0
        best_cand_idx = 0
        for m, row in enumerate(sim_matrix):
            for k, val in enumerate(row):
                if val > max_sim:
                    max_sim = val
                    best_cand_idx = k

        # 2. Multi-view coverage across query images
        query_best_matches = [max(row) for row in sim_matrix]
        coverage_sim = sum(query_best_matches) / len(query_best_matches)

        # 3. Final aggregated score
        agg_similarity = (0.80 * max_sim) + (0.20 * coverage_sim)
        match_score = round(agg_similarity * 100, 2)

        best_image = cand_images[best_cand_idx] if cand_images else None
        best_image_path = best_image.image_path if best_image else None
        best_image_url = (
            f"/{best_image_path}"
            if best_image_path and not best_image_path.startswith("/")
            else best_image_path
        )

        event_date_str = (
            candidate.event_date.isoformat()
            if candidate.event_date is not None
            else None
        )

        try:
            from app.extensions.attribute_matching.service import get_or_create_attributes
            cand_attrs = get_or_create_attributes(db, candidate)
            cand_attrs_dict = cand_attrs.model_dump()
        except Exception:
            cand_attrs_dict = None

        ranked.append(
            {
                "report_id": candidate.id,
                "item_name": candidate.item_name,
                "category": candidate.category,
                "report_type": candidate.report_type,
                "location_text": candidate.location_text,
                "event_date": event_date_str,
                "description": candidate.description,
                "color": candidate.color,
                "brand": candidate.brand,
                "model": candidate.model,
                "match_score": match_score,
                "similarity_score": round(agg_similarity, 4),
                "best_image_path": best_image_path,
                "best_image_url": best_image_url,
                "candidate_image_count": len(cand_images),
                "attributes": cand_attrs_dict,
            }
        )

    # Sort descending by match_score, breaking ties by report_id
    ranked.sort(
        key=lambda item: (
            item["match_score"],
            item["report_id"],
        ),
        reverse=True,
    )

    return {
        "query_image_count": len(query_vectors),
        "candidate_count": len(ranked),
        "matches": ranked[:limit],
    }

