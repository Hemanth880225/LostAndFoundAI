"""API Router for Product-Link Metadata Extraction and Item Enrichment."""

from fastapi import APIRouter, HTTPException, status
from app.extensions.product_links.schemas import ProductLinkRequest, ProductMetadata
from app.extensions.product_links.service import extract_product_metadata

router = APIRouter(
    prefix="/api/product-links",
    tags=["Product Links & Enrichment"],
)


@router.post(
    "/enrich",
    response_model=ProductMetadata,
    summary="Extract product metadata from an e-commerce URL",
    description="Safely fetches public product title, brand, color, category, and estimated price with SSRF protection.",
)
async def enrich_product_link_endpoint(payload: ProductLinkRequest):
    """
    Extract item details from an optional product URL.
    Fails safely without raising fatal exceptions if the external site is inaccessible.
    """
    return await extract_product_metadata(url=payload.url)
