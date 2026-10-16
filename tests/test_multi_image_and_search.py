from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai.similarity import normalized_similarity
from app.db.database import Base, get_db
from app.db.models import ItemEmbedding, ItemImage, ItemReport
from app.main import app
from app.routers import images as images_router
from app.services.matching_service import find_matches, find_matches_by_image


def image_bytes(image_format="PNG", size=(32, 32), color="black"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def test_setup(tmp_path, monkeypatch):
    """Set up an in-memory SQLite database and temporary upload directory."""
    db_file = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)

    TestingSessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(images_router, "UPLOAD_DIR", upload_dir)

    with TestClient(app) as client:
        yield client, TestingSessionLocal, upload_dir, db_file

    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def create_report(db, report_type="found", item_name="Blue Backpack", status="active"):
    report = ItemReport(
        report_type=report_type,
        item_name=item_name,
        category="Bags",
        color="blue",
        brand="Eastpak",
        model="Padded Pak'r",
        description="A durable blue canvas backpack found in the cafeteria.",
        event_date=date(2026, 10, 12),
        location_text="Campus Cafeteria",
        latitude=18.5204,
        longitude=73.8567,
        status=status,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


# Case 1: Upload one image against a report
def test_case_1_upload_one_image_against_report(test_setup):
    client, session_factory, upload_dir, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    img_data = image_bytes("PNG")
    response = client.post(
        f"/api/reports/{rep_id}/images",
        files={"file": ("front.png", img_data, "image/png")},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["report_id"] == rep_id
    assert "uploads/" in data["image_path"]
    assert data["content_type"] == "image/png"
    assert data["original_filename"] == "front.png"

    saved_file = upload_dir / Path(data["image_path"]).name
    assert saved_file.exists()

    with session_factory() as db:
        rec = db.get(ItemImage, data["id"])
        assert rec is not None
        assert rec.report_id == rep_id
        assert rec.original_filename == "front.png"


# Case 2: Upload several images against one report
def test_case_2_upload_several_images_against_one_report(test_setup):
    client, session_factory, upload_dir, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    files = [
        ("files", ("front.png", image_bytes("PNG", color="red"), "image/png")),
        ("files", ("back.jpg", image_bytes("JPEG", color="blue"), "image/jpeg")),
        ("files", ("label.webp", image_bytes("WEBP", color="green"), "image/webp")),
    ]

    response = client.post(f"/api/reports/{rep_id}/images/batch", files=files)
    assert response.status_code == 201
    data = response.json()

    assert data["report_id"] == rep_id
    assert data["total"] == 3
    assert data["successful_count"] == 3
    assert data["failed_count"] == 0
    assert len(data["images"]) == 3

    # Verify all 3 images belong to the same report
    with session_factory() as db:
        records = db.scalars(select(ItemImage).where(ItemImage.report_id == rep_id)).all()
        assert len(records) == 3
        filenames = {r.original_filename for r in records}
        assert filenames == {"front.png", "back.jpg", "label.webp"}
        for r in records:
            assert r.report_id == rep_id
            assert (upload_dir / Path(r.image_path).name).exists()


# Case 3: Retrieve a report and verify that all its images are present
def test_case_3_retrieve_report_and_verify_all_images_present(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    files = [
        ("files", ("img1.png", image_bytes("PNG"), "image/png")),
        ("files", ("img2.jpg", image_bytes("JPEG"), "image/jpeg")),
    ]
    client.post(f"/api/reports/{rep_id}/images/batch", files=files)

    # 1. Retrieve images endpoint
    res_images = client.get(f"/api/reports/{rep_id}/images")
    assert res_images.status_code == 200
    images_list = res_images.json()
    assert len(images_list) == 2
    assert images_list[0]["original_filename"] in {"img1.png", "img2.jpg"}
    assert images_list[0]["url"].startswith("/uploads/")

    # 2. Retrieve report endpoint
    res_report = client.get(f"/api/reports/{rep_id}")
    assert res_report.status_code == 200
    report_data = res_report.json()
    assert len(report_data["images"]) == 2


# Case 4: Restart the application and verify that persisted image references and embeddings remain available
def test_case_4_restart_application_persistence(test_setup, tmp_path, monkeypatch):
    client, session_factory, upload_dir, db_file = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    # Upload image
    upload_res = client.post(
        f"/api/reports/{rep_id}/images",
        files={"file": ("persisted.png", image_bytes("PNG"), "image/png")},
    )
    assert upload_res.status_code == 201
    img_id = upload_res.json()["id"]

    # Simulate restart by creating a new engine pointing to the same sqlite db file
    engine2 = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    NewSessionLocal = sessionmaker(bind=engine2, autoflush=False, autocommit=False)

    def override_get_db2():
        db = NewSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db2

    try:
        with TestClient(app) as client2:
            res = client2.get(f"/api/reports/{rep_id}/images")
            assert res.status_code == 200
            data = res.json()
            assert len(data) == 1
            assert data[0]["id"] == img_id
            assert data[0]["original_filename"] == "persisted.png"
            assert (upload_dir / Path(data[0]["image_path"]).name).exists()
    finally:
        app.dependency_overrides[get_db] = session_factory
        engine2.dispose()


# Case 5: Upload a mixture of valid and invalid image files
def test_case_5_upload_mixture_of_valid_and_invalid_files(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    files = [
        ("files", ("valid1.png", image_bytes("PNG"), "image/png")),
        ("files", ("invalid.txt", b"This is not a real image", "text/plain")),
        ("files", ("valid2.jpg", image_bytes("JPEG"), "image/jpeg")),
    ]

    response = client.post(f"/api/reports/{rep_id}/images/batch", files=files)
    assert response.status_code == 201
    data = response.json()

    assert data["total"] == 3
    assert data["successful_count"] == 2
    assert data["failed_count"] == 1
    assert len(data["images"]) == 2
    assert len(data["failures"]) == 1
    assert data["failures"][0]["filename"] == "invalid.txt"


# Case 6: Retry a failed image without creating a duplicate report
def test_case_6_retry_failed_image_without_creating_duplicate_report(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    # 1. Initial attempt: 1 valid, 1 invalid
    files_initial = [
        ("files", ("valid.png", image_bytes("PNG"), "image/png")),
        ("files", ("corrupted.jpg", b"corrupt bytes", "image/jpeg")),
    ]
    res1 = client.post(f"/api/reports/{rep_id}/images/batch", files=files_initial)
    assert res1.status_code == 201
    assert res1.json()["successful_count"] == 1
    assert res1.json()["failed_count"] == 1

    # 2. Retry with corrected valid file on the same report
    files_retry = [
        ("files", ("fixed.jpg", image_bytes("JPEG"), "image/jpeg")),
    ]
    res2 = client.post(f"/api/reports/{rep_id}/images/batch", files=files_retry)
    assert res2.status_code == 201
    assert res2.json()["successful_count"] == 1

    # Verify no duplicate reports exist and report has both valid images
    with session_factory() as db:
        all_reports = db.scalars(select(ItemReport)).all()
        assert len(all_reports) == 1
        assert all_reports[0].id == rep_id

        report_images = db.scalars(select(ItemImage).where(ItemImage.report_id == rep_id)).all()
        assert len(report_images) == 2


# Case 7: Search using one image and no textual input
def test_case_7_search_using_one_image_and_no_text(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db, report_type="found", item_name="Navy Backpack")
        rep_id = rep.id

    client.post(
        f"/api/reports/{rep_id}/images",
        files={"file": ("target.png", image_bytes("PNG", color="navy"), "image/png")},
    )

    # Search with 1 image alone
    query = image_bytes("PNG", color="navy")
    res = client.post(
        "/api/reports/search-by-image",
        files={"file": ("query.png", query, "image/png")},
    )

    assert res.status_code == 200
    data = res.json()
    assert data["query_image_count"] == 1
    assert data["candidate_count"] >= 1
    assert len(data["matches"]) >= 1
    top = data["matches"][0]
    assert top["report_id"] == rep_id
    assert top["item_name"] == "Navy Backpack"
    assert top["match_score"] > 0
    assert top["best_image_url"] is not None

    # Verify no unwanted report was created for the search query
    with session_factory() as db:
        reports = db.scalars(select(ItemReport)).all()
        assert len(reports) == 1


# Case 8: Search using multiple query images and no textual input
def test_case_8_search_using_multiple_query_images_and_no_text(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db, report_type="found", item_name="Leather Wallet")
        rep_id = rep.id

    client.post(
        f"/api/reports/{rep_id}/images",
        files={"file": ("wallet.jpg", image_bytes("JPEG", color="brown"), "image/jpeg")},
    )

    files = [
        ("files", ("front.jpg", image_bytes("JPEG", color="brown"), "image/jpeg")),
        ("files", ("back.jpg", image_bytes("JPEG", color="brown"), "image/jpeg")),
    ]

    res = client.post("/api/reports/search-by-image", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["query_image_count"] == 2
    assert len(data["matches"]) >= 1
    assert data["matches"][0]["report_id"] == rep_id


# Case 9: Retrieve candidates from actual stored database embeddings
def test_case_9_retrieve_candidates_from_actual_stored_database_embeddings(test_setup):
    client, session_factory, _, _ = test_setup
    fake_vector = [0.05] * 512

    with session_factory() as db:
        rep = create_report(db, report_type="lost", item_name="Silver Keyring")
        img = ItemImage(
            report_id=rep.id,
            image_path="uploads/dummy.png",
            original_filename="dummy.png",
            content_type="image/png",
        )
        db.add(img)
        db.commit()
        db.refresh(img)

        # Explicitly save embedding in item_embeddings table
        emb = ItemEmbedding(
            report_id=rep.id,
            image_id=img.id,
            embedding_type="image",
            vector=fake_vector,
            model_name=images_router.MODEL_NAME,
        )
        db.add(emb)
        db.commit()

        # Call find_matches_by_image directly with matching vector
        result = find_matches_by_image(db, query_vectors=[fake_vector], target_type="lost")
        assert result["candidate_count"] == 1
        assert result["matches"][0]["report_id"] == rep.id
        assert result["matches"][0]["match_score"] == 100.0


# Case 10: Verify that reports with multiple images are deduplicated in search results
def test_case_10_reports_with_multiple_images_are_deduplicated(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep_a = create_report(db, report_type="found", item_name="Multi-Photo Item")
        rep_b = create_report(db, report_type="found", item_name="Single-Photo Item")
        id_a, id_b = rep_a.id, rep_b.id

    # Report A has 3 photos
    client.post(
        f"/api/reports/{id_a}/images/batch",
        files=[
            ("files", ("a1.png", image_bytes("PNG", color="red"), "image/png")),
            ("files", ("a2.png", image_bytes("PNG", color="red"), "image/png")),
            ("files", ("a3.png", image_bytes("PNG", color="red"), "image/png")),
        ],
    )

    # Report B has 1 photo
    client.post(
        f"/api/reports/{id_b}/images",
        files={"file": ("b1.png", image_bytes("PNG", color="blue"), "image/png")},
    )

    res = client.post(
        "/api/reports/search-by-image",
        files={"file": ("query.png", image_bytes("PNG", color="red"), "image/png")},
    )
    assert res.status_code == 200
    matches = res.json()["matches"]

    # Verify each report appears at most once
    report_ids = [m["report_id"] for m in matches]
    assert len(report_ids) == len(set(report_ids))
    assert id_a in report_ids

    # Verify score is bounded in [0, 100]
    for m in matches:
        assert 0.0 <= m["match_score"] <= 100.0


# Case 11: Handle an empty database
def test_case_11_handle_empty_database(test_setup):
    client, _, _, _ = test_setup
    res = client.post(
        "/api/reports/search-by-image",
        files={"file": ("query.png", image_bytes("PNG"), "image/png")},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["candidate_count"] == 0
    assert data["matches"] == []


# Case 12: Handle missing embeddings and embedding-generation failures
def test_case_12_handle_missing_embeddings_and_generation_failures(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        # Add an image record pointing to a non-existent file
        img = ItemImage(
            report_id=rep.id,
            image_path="uploads/missing_file.png",
            content_type="image/png",
        )
        db.add(img)
        db.commit()

        # Searching should safely skip this candidate without error
        res = client.post(
            "/api/reports/search-by-image",
            files={"file": ("query.png", image_bytes("PNG"), "image/png")},
        )
        assert res.status_code == 200
        assert res.json()["candidate_count"] == 0


# Case 13: Handle corrupt files and unsupported formats
def test_case_13_handle_corrupt_files_and_unsupported_formats(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        rep = create_report(db)
        rep_id = rep.id

    # 1. Corrupt file in search
    res_search = client.post(
        "/api/reports/search-by-image",
        files={"file": ("corrupt.png", b"not an image", "image/png")},
    )
    assert res_search.status_code == 415

    # 2. Unsupported format (e.g. BMP) in upload
    res_upload = client.post(
        f"/api/reports/{rep_id}/images",
        files={"file": ("image.bmp", image_bytes("BMP"), "image/bmp")},
    )
    assert res_upload.status_code == 415

    # 3. Empty file in search
    res_empty = client.post(
        "/api/reports/search-by-image",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert res_empty.status_code == 400


# Case 14: Confirm that existing text-and-metadata matching continues to work
def test_case_14_existing_text_and_metadata_matching_works(test_setup):
    client, session_factory, _, _ = test_setup
    with session_factory() as db:
        lost = create_report(db, report_type="lost", item_name="Lost Blue Eastpak")
        found = create_report(db, report_type="found", item_name="Found Blue Eastpak")
        lost_id = lost.id

    res = client.get(f"/api/reports/{lost_id}/matches")
    assert res.status_code == 200
    data = res.json()
    assert data["candidate_count"] >= 1
    assert data["matches"][0]["report_id"] == found.id
    assert "reasoning" in data["matches"][0]
    assert data["matches"][0]["match_score"] > 50


# Case 15: Confirm that existing API and backend tests continue to pass
# (Will be verified via pytest run covering all existing + new test files)
