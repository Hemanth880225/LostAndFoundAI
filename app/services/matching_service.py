
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
from app.db.models import ItemEmbedding, ItemImage, ItemReport
from app.services.embedding_service import (
    get_embedding,
    save_embedding,
)


from app.ai.rule_engine import evaluate_match



def report_text(report: ItemReport) -> str:
    """Build a consistent text representation of a report."""
    return " ".join(
        str(value)
        for value in (
            report.item_name,
            report.category,
            report.brand,
            report.model,
            report.color,
            report.description,
        )
        if value
    )


def get_or_create_text_embedding(
    db: Session,
    report: ItemReport,
) -> list[float]:
    """Reuse a stored text vector or generate it once."""
    vector = get_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        model_name=MODEL_NAME,
    )

    if vector is not None:
        return vector

    vector = encode_text(report_text(report))

    save_embedding(
        db=db,
        report_id=report.id,
        embedding_type="text",
        vector=vector,
        model_name=MODEL_NAME,
    )

    return vector


def get_or_create_image_embeddings(
    db: Session,
    report: ItemReport,
) -> list[list[float]]:
    """Return stored image vectors, generating missing ones."""
    images = db.scalars(
        select(ItemImage).where(
            ItemImage.report_id == report.id
        )
    ).all()

    vectors = []

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
            vectors.append(stored.vector)
            continue

        image_path = image.image_path

        # Uploads are stored relative to the project root.
        from pathlib import Path

        project_root = Path(__file__).resolve().parents[2]
        absolute_path = project_root / image_path

        vector = encode_image(absolute_path)

        save_embedding(
            db=db,
            report_id=report.id,
            image_id=image.id,
            embedding_type="image",
            vector=vector,
            model_name=MODEL_NAME,
        )

        vectors.append(vector)

    return vectors


def score_candidate(
    db: Session,
    lost: ItemReport,
    found: ItemReport,
) -> dict:
    """Calculate available AI and metadata similarity signals."""
    lost_text = get_or_create_text_embedding(db, lost)
    found_text = get_or_create_text_embedding(db, found)

    text_score = normalized_similarity(
        lost_text,
        found_text,
    )

    lost_images = get_or_create_image_embeddings(db, lost)
    found_images = get_or_create_image_embeddings(db, found)

    image_score = None

    if lost_images and found_images:
        image_score = max(
            normalized_similarity(a, b)
            for a in lost_images
            for b in found_images
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
        "location": location_score,
        "time": time_score,
    }

    if image_score is not None:
        components["image"] = image_score

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
    report = db.get(ItemReport, report_id)

    if report is None:
        raise ValueError("Report not found.")

    if report.status != "active":
        raise ValueError("Only active reports can be matched.")

    opposite_type = (
        "found" if report.report_type == "lost" else "lost"
    )

    statement = select(ItemReport).where(
        ItemReport.report_type == opposite_type,
        ItemReport.status == "active",
        ItemReport.category == report.category,
    )

    candidates = db.scalars(statement).all()
    ranked = []

    for candidate in candidates:
        if report.report_type == "lost":
            lost, found = report, candidate
        else:
            lost, found = candidate, report

        # 1. Calculate similarity scores.
        result = score_candidate(db, lost, found)

        # 2. Apply our three reasoning techniques.
        reasoning = evaluate_match(
            lost=lost,
            found=found,
            components=result["components"],
        )

        # 3. Store the candidate and its explanations.
        ranked.append({
            "report_id": candidate.id,
            "item_name": candidate.item_name,
            "category": candidate.category,
            "report_type": candidate.report_type,
            "location_text": candidate.location_text,
            "event_date": candidate.event_date.isoformat(),
            "match_score": result["score"],
            "score_components": result["components"],
            "reasoning": reasoning,
        })

    # Put rule-supported candidates first.
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
