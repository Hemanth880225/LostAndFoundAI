
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import ItemImage, ItemReport


import logging

from app.ai.clip_model import MODEL_NAME
from app.ai.image_embeddings import encode_image
from app.services.embedding_service import save_embedding

logger = logging.getLogger(__name__)





router = APIRouter(
    prefix="/api/reports",
    tags=["Images"],
)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MiB

ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


@router.post("/{report_id}/images", status_code=201)
async def upload_image(
    report_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    report = db.get(ItemReport, report_id)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found.",
        )

    contents = await file.read(MAX_IMAGE_SIZE + 1)

    if not contents:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    if len(contents) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Image must not exceed 5 MiB.",
        )

    try:
        with Image.open(BytesIO(contents)) as image:
            image_format = image.format
            image.verify()

        if image_format not in ALLOWED_FORMATS:
            raise HTTPException(
                status_code=415,
                detail="Only JPEG, PNG, and WebP images are supported.",
            )

        with Image.open(BytesIO(contents)) as image:
            if image.width * image.height > 20_000_000:
                raise HTTPException(
                    status_code=413,
                    detail="Image dimensions are too large.",
                )

    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        raise HTTPException(
            status_code=415,
            detail="The uploaded file is not a valid supported image.",
        )

    extension, content_type = ALLOWED_FORMATS[image_format]
    filename = f"{uuid4().hex}.{extension}"

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / filename

    try:
        destination.write_bytes(contents)

        record = ItemImage(
            report_id=report_id,
            image_path=f"uploads/{filename}",
            content_type=content_type,
        )

        db.add(record)
        db.commit()
        db.refresh(record)

        embedding_status = "pending"

        try:
            vector = encode_image(destination)

            save_embedding(
                db=db,
                report_id=report_id,
                image_id=record.id,
                embedding_type="image",
                vector=vector,
                model_name=MODEL_NAME,
            )

            embedding_status = "ready"

        except Exception:
            logger.exception(
                "Image uploaded, but embedding generation failed "
                "for image_id=%s",
                record.id,
            )


            

    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Could not save the image.",
        )

    return {
        "id": record.id,
        "report_id": record.report_id,
        "image_path": record.image_path,
        "content_type": record.content_type,
        "message": "Image uploaded successfully.",
    }
