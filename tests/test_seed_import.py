"""
Comprehensive tests verifying the imported seed dataset:
- Database row counts, relationships, and image path resolution.
- CLIP embeddings integrity (dimensions and associations).
- REST API report listing and report detail retrieval.
- Multi-modal matching service retrieval of imported found candidates.
- Integrity of existing pre-import records.
"""

from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import ItemEmbedding, ItemImage, ItemReport
from app.extensions.attribute_matching.models import ItemAttributeRecord
from app.main import app
from app.services.matching_service import find_matches

client = TestClient(app)
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_pre_existing_records_preserved():
    """Verify that report 1 (pre-existing 'Nothing Phone2' lost report) is preserved intact."""
    with SessionLocal() as db:
        rep1 = db.get(ItemReport, 1)
        assert rep1 is not None, "Report ID 1 must exist"
        assert rep1.report_type == "lost"
        assert "Nothing Phone2" in rep1.item_name


def test_seed_reports_count_and_types():
    """Verify that exactly 8 found-item seed reports were imported (IDs 2 through 9)."""
    with SessionLocal() as db:
        found_reports = db.scalars(
            select(ItemReport).where(ItemReport.report_type == "found").order_by(ItemReport.id)
        ).all()

        assert len(found_reports) == 8, f"Expected 8 found reports, found {len(found_reports)}"
        ids = [r.id for r in found_reports]
        assert ids == [2, 3, 4, 5, 6, 7, 8, 9]

        expected_titles = [
            "White Wireless Earbuds with Charging Case",
            "Dark Blue/Black WROGN Backpack",
            "Silver HP Laptop",
            "White 80W Charger with Cable",
            "Black John Jacobs Eyeglasses",
            "Black Bluetooth Neckband Earphones",
            "Grey American Tourister Backpack",
            "Black ART LINK A4 Longbook",
        ]
        for report, expected_title in zip(found_reports, expected_titles):
            assert report.item_name == expected_title
            assert report.status == "active"


def test_seed_images_and_file_existence():
    """Verify that all 15 associated images exist in database and resolve to physical files on disk."""
    with SessionLocal() as db:
        images = db.scalars(
            select(ItemImage).where(ItemImage.report_id >= 2).order_by(ItemImage.id)
        ).all()

        assert len(images) == 15, f"Expected 15 images for seed items, found {len(images)}"

        # Check per-report image distribution: [3, 2, 2, 1, 2, 1, 2, 2]
        expected_counts = {2: 3, 3: 2, 4: 2, 5: 1, 6: 2, 7: 1, 8: 2, 9: 2}
        counts = {}
        for img in images:
            counts[img.report_id] = counts.get(img.report_id, 0) + 1
            # Verify file exists on disk
            img_file = PROJECT_ROOT / img.image_path
            assert img_file.is_file(), f"Image file missing on disk: {img_file}"
            assert img_file.stat().st_size > 1000, f"Image file suspiciously small: {img_file}"
            assert img.content_type == "image/jpeg"

        assert counts == expected_counts, f"Counts mismatch: {counts} vs {expected_counts}"


def test_clip_embeddings_integrity():
    """Verify that CLIP embeddings exist for all 15 images and 8 text descriptions."""
    with SessionLocal() as db:
        seed_report_ids = [2, 3, 4, 5, 6, 7, 8, 9]
        # Image embeddings
        img_embeddings = db.scalars(
            select(ItemEmbedding).where(
                ItemEmbedding.report_id.in_(seed_report_ids),
                ItemEmbedding.embedding_type == "image",
            )
        ).all()
        assert len(img_embeddings) == 15, f"Expected 15 image embeddings, found {len(img_embeddings)}"
        for emb in img_embeddings:
            assert emb.image_id is not None
            assert len(emb.vector) == 512, "CLIP vector must be 512 dimensions"
            assert emb.model_name == "openai/clip-vit-base-patch32"

        # Text embeddings
        txt_embeddings = db.scalars(
            select(ItemEmbedding).where(
                ItemEmbedding.report_id.in_(seed_report_ids),
                ItemEmbedding.embedding_type == "text",
            )
        ).all()
        assert len(txt_embeddings) == 8, f"Expected 8 text embeddings, found {len(txt_embeddings)}"
        for emb in txt_embeddings:
            assert emb.image_id is None
            assert len(emb.vector) == 512, "CLIP text vector must be 512 dimensions"


def test_attribute_records_persisted():
    """Verify that ItemAttributeRecord exists for all 8 seed items with appropriate categories."""
    with SessionLocal() as db:
        seed_report_ids = [2, 3, 4, 5, 6, 7, 8, 9]
        records = db.scalars(
            select(ItemAttributeRecord).where(ItemAttributeRecord.report_id.in_(seed_report_ids))
        ).all()
        assert len(records) == 8, f"Expected 8 attribute records, found {len(records)}"

        records_by_id = {r.report_id: r for r in records}
        # Check F002 (WROGN Backpack)
        assert records_by_id[3].category == "Backpack"
        assert records_by_id[3].primary_color == "Dark Blue"

        # Check F003 (HP Laptop)
        assert records_by_id[4].category == "Laptop"
        assert records_by_id[4].primary_color == "Silver"

        # Check F005 (John Jacobs Eyeglasses)
        assert records_by_id[6].category == "Glasses"
        assert records_by_id[6].primary_color == "Black"


def test_api_list_and_detail_endpoints():
    """Verify REST API returns the imported found items."""
    # List found items
    response = client.get("/api/reports?report_type=found&limit=20")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 8
    titles = [item["item_name"] for item in data]
    assert "White Wireless Earbuds with Charging Case" in titles
    assert "Silver HP Laptop" in titles
    assert "Grey American Tourister Backpack" in titles

    # Detail view for F003 (HP Laptop)
    detail_res = client.get("/api/reports/4")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["item_name"] == "Silver HP Laptop"
    assert detail["brand"] == "HP"
    assert len(detail["images"]) == 2


def test_matching_service_finds_imported_candidates():
    """Verify the AI matching service retrieves imported found items for corresponding query reports."""
    with SessionLocal() as db:
        # Create a temporary lost report for testing match retrieval against imported found items
        temp_lost = ItemReport(
            report_type="lost",
            item_name="Lost HP Pavilion Laptop Silver",
            category="Laptop",
            color="Silver",
            brand="HP",
            description="Lost my silver HP laptop near campus library. Has stickers and silver lid.",
            location_text="Library reading hall",
            event_date=date.fromisoformat("2026-10-16"),
            status="active",
        )
        db.add(temp_lost)
        db.commit()
        db.refresh(temp_lost)

        try:
            result = find_matches(db=db, report_id=temp_lost.id, limit=5)
            matches = result["matches"]
            assert len(matches) > 0, "Matching service should return candidates"

            candidate_ids = [m["report_id"] for m in matches]
            # Report 4 is the Silver HP Laptop!
            assert 4 in candidate_ids, f"Report 4 (Silver HP Laptop) should be in candidate matches: {candidate_ids}"

            # Verify report 4 match score details
            hp_match = next(m for m in matches if m["report_id"] == 4)
            assert hp_match["match_score"] > 0.50, f"Expected strong match score, got {hp_match['match_score']}"
            assert hp_match["reasoning"]["plausible_match"] is True
        finally:
            from sqlalchemy import delete
            db.execute(delete(ItemEmbedding).where(ItemEmbedding.report_id == temp_lost.id))
            db.execute(delete(ItemAttributeRecord).where(ItemAttributeRecord.report_id == temp_lost.id))
            db.delete(temp_lost)
            db.commit()
