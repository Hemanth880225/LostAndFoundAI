
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

from app.ai.image_embeddings import encode_image
from app.db.database import get_db
from app.db.models import ItemReport
from app.routers.images import validate_image_file
from app.schemas.reports import ItemReportCreate, ItemReportResponse
from app.services.matching_service import find_matches, find_matches_by_image
from app.services.report_service import (
    create_report,
    get_report,
    list_reports,
)


router = APIRouter(
    prefix="/api/reports",
    tags=["Reports"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post(
    "",
    response_model=ItemReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_report_endpoint(
    payload: ItemReportCreate,
    db: DatabaseSession,
):
    """Create a new lost-item or found-item report."""

    try:
        return create_report(db=db, payload=payload)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create the report.",
        ) from exc


@router.get("", response_model=list[ItemReportResponse])
def list_reports_endpoint(
    db: DatabaseSession,
    report_type: Annotated[
        str | None,
        Query(description="Filter by 'lost' or 'found'."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """List reports, optionally filtered by report type."""

    try:
        return list_reports(
            db=db,
            report_type=report_type,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/search-by-image")
async def search_by_image_endpoint(
    request: Request,
    db: DatabaseSession,
    target_type: Annotated[
        str | None,
        Query(description="Filter candidate reports by 'lost' or 'found'."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """
    Find candidate reports using one or more query images alone.
    No textual input or report creation required.
    """
    form = await request.form()
    all_files = []
    for key in ("files", "file", "images", "image"):
        for val in form.getlist(key):
            if hasattr(val, "filename") and hasattr(val, "read") and val not in all_files:
                all_files.append(val)


    if not all_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one query image must be provided.",
        )

    # Validate each image and extract normalized CLIP vectors
    query_vectors = []
    first_image_bytes = None
    for item in all_files:
        contents, ext, c_type = await validate_image_file(item)
        if first_image_bytes is None:
            first_image_bytes = contents
        try:
            vector = encode_image(contents)
            query_vectors.append(vector)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Could not generate visual embedding for query image {item.filename}: {exc}",
            ) from exc

    try:
        result = find_matches_by_image(
            db=db,
            query_vectors=query_vectors,
            target_type=target_type,
            limit=limit,
        )
        if first_image_bytes is not None:
            try:
                from app.extensions.attribute_matching.extractor import extract_attributes_from_image
                q_attrs = extract_attributes_from_image(first_image_bytes)
                result["query_detected_attributes"] = q_attrs.model_dump()
            except Exception:
                pass
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc



@router.get("/{report_id}/matches")
def find_matches_endpoint(
    report_id: int,
    db: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
):
    """Find and rank possible matches for a report."""

    try:
        return find_matches(
            db=db,
            report_id=report_id,
            limit=limit,
        )
    except ValueError as exc:
        message = str(exc)

        if "not found" in message.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=message,
            ) from exc

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from exc


@router.get("/{report_id}", response_model=ItemReportResponse)
def get_report_endpoint(
    report_id: int,
    db: DatabaseSession,
):
    """Retrieve a report by its ID."""

    report = get_report(db=db, report_id=report_id)

    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found.",
        )

    return report
