"""Pydantic schemas for Product-Link Metadata Extraction and Enrichment."""

from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class ProductLinkRequest(BaseModel):
    """Incoming request to extract metadata from an e-commerce or product page."""
    url: str = Field(min_length=8, max_length=1000, description="Web URL of the product.")


class ProductMetadata(BaseModel):
    """Enriched product attributes extracted from the page."""
    title: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    color: Optional[str] = None
    category: Optional[str] = None
    estimated_price_rupees: Optional[float] = None
    image_url: Optional[str] = None
    canonical_url: str
    source_domain: str
    extraction_status: str = Field(
        default="success",
        description="Status: 'success', 'partial', or 'failed'",
    )
    error_message: Optional[str] = None
