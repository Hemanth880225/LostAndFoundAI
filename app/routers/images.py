
import logging
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.clip_model import MODEL_NAME
from app.ai.image_embeddings import encode_image
from app.db.database import get_db
from app.db.models import ItemEmbedding, ItemImage, ItemReport
from app.services.embedding_service import save_embedding


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reports",
    tags=["Images"],
)

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
MAX_IMAGE_SIZE = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_BATCH_IMAGES = 10

ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}


async def validate_image_file(file: UploadFile) -> tuple[bytes, str, str]:
    """Validate image file contents, format, and dimensions."""
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
            if image.width * image.height > MAX_IMAGE_PIXELS:
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
    ) as exc:
        raise HTTPException(
            status_code=415,
            detail="The uploaded file is not a valid supported image.",
        ) from exc

    extension, content_type = ALLOWED_FORMATS[image_format]
    return contents, extension, content_type


def persist_image_and_embed(
    db: Session,
    report_id: int,
    contents: bytes,
    extension: str,
    content_type: str,
    original_filename: str | None = None,
) -> dict:
    """Save the image to storage, create a database record, and attempt embedding."""
    filename = f"{uuid4().hex}.{extension}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / filename

    record = None
    record_committed = False

    try:
        destination.write_bytes(contents)

        record = ItemImage(
            report_id=report_id,
            image_path=f"uploads/{filename}",
            original_filename=original_filename,
            content_type=content_type,
        )

        db.add(record)
        db.commit()
        record_committed = True
        db.refresh(record)

    except Exception as exc:
        db.rollback()
        if not record_committed:
            destination.unlink(missing_ok=True)

        logger.exception(
            "Could not save uploaded image for report_id=%s",
            report_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Could not save the image.",
        ) from exc

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
            "Image uploaded, but embedding generation failed for image_id=%s",
            record.id,
        )

    return {
        "id": record.id,
        "report_id": record.report_id,
        "image_path": record.image_path,
        "url": f"/{record.image_path}",
        "original_filename": record.original_filename,
        "content_type": record.content_type,
        "embedding_status": embedding_status,
        "created_at": record.created_at.isoformat(),
        "message": "Image uploaded successfully.",
    }


@router.get("/{report_id}/images")
def list_report_images(
    report_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve all images associated with a report."""
    report = db.get(ItemReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found.",
        )

    images = db.scalars(
        select(ItemImage)
        .where(ItemImage.report_id == report_id)
        .order_by(ItemImage.id.asc())
    ).all()

    results = []
    for img in images:
        has_embedding = db.scalars(
            select(ItemEmbedding).where(
                ItemEmbedding.report_id == report_id,
                ItemEmbedding.image_id == img.id,
                ItemEmbedding.embedding_type == "image",
                ItemEmbedding.model_name == MODEL_NAME,
            )
        ).first() is not None

        results.append(
            {
                "id": img.id,
                "report_id": img.report_id,
                "image_path": img.image_path,
                "url": f"/{img.image_path}" if not img.image_path.startswith("/") else img.image_path,
                "original_filename": img.original_filename,
                "content_type": img.content_type,
                "embedding_status": "ready" if has_embedding else "pending",
                "created_at": img.created_at.isoformat(),
            }
        )

    return results


@router.post("/{report_id}/images", status_code=201)
async def upload_image(
    report_id: int,
    request: Request,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """
    Validate, store, and generate embeddings for uploaded image(s).
    Supports single-image upload (returning the classic image dict)
    and multi-image upload with partial-success reporting.
    """
    report = db.get(ItemReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found.",
        )

    if report.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Images can only be added to active reports.",
        )

    # Gather all uploaded files across form field aliases
    form = await request.form()
    all_files: list[UploadFile] = []

    # Check request form first for multiple files under any expected key
    for key in ("files", "file", "images", "image"):
        values = form.getlist(key)
        for val in values:
            if hasattr(val, "filename") and hasattr(val, "read") and val not in all_files:
                all_files.append(val)


    if not all_files:
        if file is not None:
            all_files.append(file)
        elif files:
            all_files.extend(files)

    if not all_files:
        raise HTTPException(
            status_code=400,
            detail="No image files provided.",
        )

    # If exactly one file is supplied, preserve the single-image response contract
    # and propagate any validation errors directly as HTTP exceptions.
    if len(all_files) == 1:
        single = all_files[0]
        contents, ext, c_type = await validate_image_file(single)
        return persist_image_and_embed(
            db=db,
            report_id=report_id,
            contents=contents,
            extension=ext,
            content_type=c_type,
            original_filename=single.filename,
        )

    # Multi-image handling with partial-success tolerance
    if len(all_files) > MAX_BATCH_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload more than {MAX_BATCH_IMAGES} images in one request.",
        )

    successful = []
    failed = []

    for item in all_files:
        try:
            contents, ext, c_type = await validate_image_file(item)
            saved = persist_image_and_embed(
                db=db,
                report_id=report_id,
                contents=contents,
                extension=ext,
                content_type=c_type,
                original_filename=item.filename,
            )
            successful.append(saved)
        except HTTPException as exc:
            failed.append({
                "filename": item.filename,
                "error": exc.detail,
                "status_code": exc.status_code,
            })
        except Exception as exc:
            failed.append({
                "filename": item.filename,
                "error": str(exc),
                "status_code": 500,
            })

    # If every file failed and none succeeded, return a representative error
    if not successful and failed:
        first_err = failed[0]
        raise HTTPException(
            status_code=first_err.get("status_code", 400),
            detail=f"Image upload failed for {first_err['filename']}: {first_err['error']}",
        )

    return {
        "report_id": report_id,
        "total": len(all_files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "images": successful,
        "failures": failed,
        "message": f"{len(successful)} of {len(all_files)} images uploaded successfully.",
    }


@router.post("/{report_id}/images/batch", status_code=201)
async def upload_images_batch(
    report_id: int,
    request: Request,
    files: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """
    Dedicated batch upload endpoint supporting multi-file uploads with partial-success handling.
    """
    report = db.get(ItemReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Report not found.",
        )

    if report.status != "active":
        raise HTTPException(
            status_code=400,
            detail="Images can only be added to active reports.",
        )

    form = await request.form()
    all_files: list[UploadFile] = []
    for key in ("files", "file", "images", "image"):
        values = form.getlist(key)
        for val in values:
            if hasattr(val, "filename") and hasattr(val, "read") and val not in all_files:
                all_files.append(val)


    if not all_files and files:
        all_files.extend(files)

    if not all_files:
        raise HTTPException(
            status_code=400,
            detail="No image files provided.",
        )

    if len(all_files) > MAX_BATCH_IMAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot upload more than {MAX_BATCH_IMAGES} images in one request.",
        )

    successful = []
    failed = []

    for item in all_files:
        try:
            contents, ext, c_type = await validate_image_file(item)
            saved = persist_image_and_embed(
                db=db,
                report_id=report_id,
                contents=contents,
                extension=ext,
                content_type=c_type,
                original_filename=item.filename,
            )
            successful.append(saved)
        except HTTPException as exc:
            failed.append({
                "filename": item.filename,
                "error": exc.detail,
                "status_code": exc.status_code,
            })
        except Exception as exc:
            failed.append({
                "filename": item.filename,
                "error": str(exc),
                "status_code": 500,
            })

    if not successful and failed:
        first_err = failed[0]
        raise HTTPException(
            status_code=first_err.get("status_code", 400),
            detail=f"Image upload failed for {first_err['filename']}: {first_err['error']}",
        )

    return {
        "report_id": report_id,
        "total": len(all_files),
        "successful_count": len(successful),
        "failed_count": len(failed),
        "images": successful,
        "failures": failed,
        "message": f"{len(successful)} of {len(all_files)} images uploaded successfully.",
    }
