from datetime import date
from io import BytesIO
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import ItemImage, ItemReport
from app.main import app
from app.routers import images as images_router


@pytest.fixture
def client(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
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
    monkeypatch.setattr(images_router, "UPLOAD_DIR", tmp_path / "uploads")

    try:
        with TestClient(app) as test_client:
            yield test_client, TestingSessionLocal
    finally:
        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def make_report(db, status="active"):
    report = ItemReport(
        report_type="found",
        item_name="Black phone",
        category="electronics",
        color="black",
        description="Black phone found near the library.",
        event_date=date(2026, 10, 10),
        location_text="College library",
        latitude=18.5204,
        longitude=73.8567,
        status=status,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def image_bytes(image_format="PNG", size=(32, 32)):
    buffer = BytesIO()
    Image.new("RGB", size, "black").save(buffer, format=image_format)
    return buffer.getvalue()


def upload(client, report_id, contents, filename="test.png",
           content_type="image/png"):
    return client.post(
        f"/api/reports/{report_id}/images",
        files={"file": (filename, contents, content_type)},
    )


def create_report_for_test(client_fixture, status="active"):
    _, session_factory = client_fixture
    with session_factory() as db:
        return make_report(db, status=status).id


def test_upload_rejects_missing_report(client):
    test_client, _ = client

    response = upload(test_client, 99999, image_bytes())

    assert response.status_code == 404


def test_upload_rejects_inactive_report(client):
    test_client, _ = client
    report_id = create_report_for_test(client, status="returned")

    response = upload(test_client, report_id, image_bytes())

    assert response.status_code == 400


def test_upload_rejects_empty_file(client):
    test_client, _ = client
    report_id = create_report_for_test(client)

    response = upload(test_client, report_id, b"")

    assert response.status_code == 400


def test_upload_rejects_invalid_image(client):
    test_client, _ = client
    report_id = create_report_for_test(client)

    response = upload(test_client, report_id, b"not an image")

    assert response.status_code == 415


def test_upload_rejects_unsupported_image_format(client):
    test_client, _ = client
    report_id = create_report_for_test(client)
    contents = image_bytes("BMP")

    response = upload(
        test_client, report_id, contents,
        filename="test.bmp", content_type="image/bmp",
    )

    assert response.status_code == 415


def test_upload_rejects_oversized_file(client):
    test_client, _ = client
    report_id = create_report_for_test(client)
    oversized = b"x" * (images_router.MAX_IMAGE_SIZE + 1)

    response = upload(test_client, report_id, oversized)

    assert response.status_code == 413


def test_upload_rejects_excessive_image_dimensions(client):
    test_client, _ = client
    report_id = create_report_for_test(client)
    contents = image_bytes(size=(5001, 4000))

    response = upload(test_client, report_id, contents)

    assert response.status_code == 413


def test_valid_upload_saves_image_and_reports_pending_embedding(client):
    test_client, session_factory = client
    report_id = create_report_for_test(client)

    with patch.object(
        images_router, "encode_image",
        side_effect=RuntimeError("Mock embedding failure"),
    ):
        response = upload(test_client, report_id, image_bytes())

    assert response.status_code == 201
    data = response.json()
    assert data["report_id"] == report_id
    assert data["embedding_status"] == "pending"

    upload_path = images_router.UPLOAD_DIR / data["image_path"].split("/")[-1]
    assert upload_path.exists()

    with session_factory() as db:
        record = db.get(ItemImage, data["id"])
        assert record is not None
        assert record.report_id == report_id
        assert record.content_type == "image/png"


def test_valid_upload_reports_ready_embedding(client):
    test_client, session_factory = client
    report_id = create_report_for_test(client)
    fake_vector = [0.1, 0.2, 0.3]

    with (
        patch.object(images_router, "encode_image", return_value=fake_vector),
        patch.object(images_router, "save_embedding") as save_mock,
    ):
        response = upload(test_client, report_id, image_bytes())

    assert response.status_code == 201
    data = response.json()
    assert data["embedding_status"] == "ready"

    save_mock.assert_called_once()
    assert save_mock.call_args.kwargs["report_id"] == report_id
    assert save_mock.call_args.kwargs["embedding_type"] == "image"

    with session_factory() as db:
        record = db.get(ItemImage, data["id"])
        assert record is not None


def test_upload_accepts_jpeg(client):
    test_client, _ = client
    report_id = create_report_for_test(client)

    with (
        patch.object(images_router, "encode_image", return_value=[0.1]),
        patch.object(images_router, "save_embedding"),
    ):
        response = upload(
            test_client,
            report_id,
            image_bytes("JPEG"),
            filename="test.jpg",
            content_type="image/jpeg",
        )

    assert response.status_code == 201
    assert response.json()["content_type"] == "image/jpeg"


def test_upload_accepts_webp(client):
    test_client, _ = client
    report_id = create_report_for_test(client)

    with (
        patch.object(images_router, "encode_image", return_value=[0.1]),
        patch.object(images_router, "save_embedding"),
    ):
        response = upload(
            test_client,
            report_id,
            image_bytes("WEBP"),
            filename="test.webp",
            content_type="image/webp",
        )

    assert response.status_code == 201
    assert response.json()["content_type"] == "image/webp"

