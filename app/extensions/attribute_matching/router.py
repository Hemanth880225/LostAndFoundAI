"""FastAPI router for Advanced AI Attribute-Based Recognition, Matching, and Search."""

import json
import logging
from typing import Annotated, Any, Dict, List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.db.database import get_db
from app.db.models import ItemReport
from app.extensions.attribute_matching.extractor import (
    TAXONOMY_CATEGORIES,
    TAXONOMY_DISTINCTIVE_KEYWORDS,
    TAXONOMY_MATERIALS,
    TAXONOMY_PRIMARY_COLORS,
    TAXONOMY_SHAPES,
    TAXONOMY_SIZES,
    extract_attributes_from_image,
    extract_attributes_from_text,
    merge_attributes,
)
from app.extensions.attribute_matching.schemas import (
    AttributeExtractionRequest,
    AttributeExtractionResponse,
    AttributeFilterRequest,
    AttributeSearchResponse,
    ItemAttributes,
    TaxonomyResponse,
)
from app.extensions.attribute_matching.service import (
    get_or_create_attributes,
    search_by_attributes,
)
from app.routers.images import validate_image_file

router = APIRouter(
    prefix="/api/attributes",
    tags=["Attribute-Based AI Matching"],
)

DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get(
    "/taxonomy",
    response_model=TaxonomyResponse,
    summary="Get supported physical and visual attribute vocabulary",
    description="Returns recognized categories, geometric shapes, canonical colors, materials, and distinctive feature markers.",
)
def get_attribute_taxonomy() -> TaxonomyResponse:
    """Return standard attribute taxonomy for frontend filter dropdowns and chips."""
    return TaxonomyResponse(
        categories=TAXONOMY_CATEGORIES,
        shapes=TAXONOMY_SHAPES,
        primary_colors=TAXONOMY_PRIMARY_COLORS,
        sizes=TAXONOMY_SIZES,
        materials=TAXONOMY_MATERIALS,
        common_distinctive_features=TAXONOMY_DISTINCTIVE_KEYWORDS,
    )


@router.post(
    "/extract",
    response_model=AttributeExtractionResponse,
    summary="Extract physical and visual attributes from text and/or image",
    description="Extracts multi-dimensional attributes from descriptions, titles, or uploaded photo.",
)
async def extract_attributes_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(default=None),
) -> AttributeExtractionResponse:
    """Extract physical and visual attributes from uploaded file and/or form/JSON fields."""
    content_type = request.headers.get("content-type", "")

    title = None
    description = None
    category = None
    color = None
    image_bytes = None

    if "application/json" in content_type:
        try:
            body = await request.json()
            title = body.get("title")
            description = body.get("description")
            category = body.get("category")
            color = body.get("color")
        except Exception:
            pass
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        title = form.get("title") or form.get("item_name")
        description = form.get("description")
        category = form.get("category")
        color = form.get("color")

        # Check for uploaded image file
        for key in ("file", "image", "files"):
            val = form.get(key)
            if hasattr(val, "filename") and hasattr(val, "read") and val.filename:
                try:
                    contents, _, _ = await validate_image_file(val)
                    image_bytes = contents
                    break
                except Exception:
                    pass

    if file and hasattr(file, "filename") and file.filename and not image_bytes:
        try:
            contents, _, _ = await validate_image_file(file)
            image_bytes = contents
        except Exception:
            pass

    # 1. Text-based extraction
    text_attrs = extract_attributes_from_text(
        title=str(title) if title else None,
        description=str(description) if description else None,
        category=str(category) if category else None,
        color=str(color) if color else None,
    )

    # 2. Vision-based extraction
    image_attrs = None
    if image_bytes:
        image_attrs = extract_attributes_from_image(image_bytes)

    # 3. Merge
    final_attrs = merge_attributes(text_attrs, image_attrs)

    # 4. Generate human summary
    summary_parts = []
    if final_attrs.primary_color:
        summary_parts.append(f"Color: {final_attrs.primary_color}")
    if final_attrs.shape:
        summary_parts.append(f"Shape: {final_attrs.shape}")
    if final_attrs.size_category:
        summary_parts.append(f"Size: {final_attrs.size_category}")
    if final_attrs.capacity_text or final_attrs.capacity_litres:
        summary_parts.append(f"Capacity: {final_attrs.capacity_text or f'{final_attrs.capacity_litres}L'}")
    if final_attrs.material:
        summary_parts.append(f"Material: {final_attrs.material}")
    if final_attrs.distinctive_features:
        summary_parts.append(f"Features: {', '.join(final_attrs.distinctive_features)}")

    summary_str = " · ".join(summary_parts) if summary_parts else "No distinctive attributes inferable from provided input."

    return AttributeExtractionResponse(
        attributes=final_attrs,
        summary=summary_str,
    )


@router.post(
    "/search",
    response_model=AttributeSearchResponse,
    summary="Multi-modal attribute-aware search",
    description="Search active reports using attribute filters, natural language queries, and optional query photos.",
)
async def search_attributes_endpoint(
    request: Request,
    db: DatabaseSession,
) -> AttributeSearchResponse:
    """
    Search and rank candidate reports using attribute filters, text query, and optional images.
    Supports hard filters vs soft ranking preferences.
    """
    content_type = request.headers.get("content-type", "")
    query_image_bytes: List[bytes] = []

    if "application/json" in content_type:
        body = await request.json()
        filter_req = AttributeFilterRequest(**body)
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        query_text = form.get("query_text") or form.get("q")
        category = form.get("category")
        primary_color = form.get("primary_color") or form.get("color")
        secondary_color = form.get("secondary_color")
        shape = form.get("shape")
        size_category = form.get("size_category") or form.get("size")
        material = form.get("material")
        distinctive_features = form.get("distinctive_features")
        location_text = form.get("location_text") or form.get("location")
        target_type = form.get("target_type")
        hard_filters_raw = form.getlist("hard_filters") or form.get("hard_filters")
        limit_val = int(form.get("limit") or 20)

        hard_filters = []
        if isinstance(hard_filters_raw, list):
            hard_filters = [str(x) for x in hard_filters_raw if str(x).strip()]
        elif isinstance(hard_filters_raw, str) and hard_filters_raw.strip():
            try:
                parsed = json.loads(hard_filters_raw)
                hard_filters = parsed if isinstance(parsed, list) else [hard_filters_raw]
            except Exception:
                hard_filters = [f.strip() for f in hard_filters_raw.split(",") if f.strip()]

        filter_req = AttributeFilterRequest(
            query_text=str(query_text) if query_text else None,
            category=str(category) if category else None,
            primary_color=str(primary_color) if primary_color else None,
            secondary_color=str(secondary_color) if secondary_color else None,
            shape=str(shape) if shape else None,
            size_category=str(size_category) if size_category else None,
            material=str(material) if material else None,
            distinctive_features=str(distinctive_features) if distinctive_features else None,
            location_text=str(location_text) if location_text else None,
            target_type=str(target_type) if target_type else None,
            hard_filters=hard_filters,
            limit=limit_val,
        )

        # Collect uploaded query images
        for key in ("files", "file", "images", "image"):
            for val in form.getlist(key):
                if hasattr(val, "filename") and hasattr(val, "read") and val.filename:
                    try:
                        contents, _, _ = await validate_image_file(val)
                        query_image_bytes.append(contents)
                    except Exception:
                        pass
    else:
        filter_req = AttributeFilterRequest()

    try:
        return search_by_attributes(
            db=db,
            request=filter_req,
            query_image_bytes_list=query_image_bytes,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to execute attribute search: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An error occurred while executing the search. Please verify your search inputs and try again.",
        )


@router.get(
    "/reports/{report_id}",
    response_model=ItemAttributes,
    summary="Get or extract attributes for an existing report",
    description="Retrieves persisted attributes for a report or extracts and caches them on-the-fly.",
)
def get_report_attributes_endpoint(
    report_id: int,
    db: DatabaseSession,
) -> ItemAttributes:
    """Retrieve or compute normalized attributes for an item report."""
    report = db.get(ItemReport, report_id)
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found.",
        )
    return get_or_create_attributes(db=db, report=report)
