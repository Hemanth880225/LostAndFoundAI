"""Pydantic schemas for attribute-aware AI recognition, matching, and search."""

from datetime import date
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class ItemAttributes(BaseModel):
    """Normalized multi-dimensional attributes describing physical and visual object traits."""
    model_config = ConfigDict(from_attributes=True)

    category: Optional[str] = Field(default=None, description="Inferred or verified object category (e.g. backpack, bottle, phone)")
    primary_color: Optional[str] = Field(default=None, description="Dominant primary color")
    secondary_color: Optional[str] = Field(default=None, description="Accent or secondary color")
    is_multicolor: bool = Field(default=False, description="Whether object features multicolor patterns or two-tone styling")
    shape: Optional[str] = Field(default=None, description="Geometric or profile shape (rectangular, circular, cylindrical, oval, square, rounded, irregular)")
    size_category: Optional[str] = Field(default=None, description="Relative size classification (small, medium, large, compact, oversized)")
    dimensions_text: Optional[str] = Field(default=None, description="Approximate dimensions (e.g. '15-inch', '30x20 cm')")
    capacity_litres: Optional[float] = Field(default=None, description="Volume capacity in litres for bags, bottles, or containers")
    capacity_text: Optional[str] = Field(default=None, description="Original capacity text (e.g. '20-30 litres', '750ml')")
    material: Optional[str] = Field(default=None, description="Observable texture/material (leather-like, fabric/canvas, plastic, metal, transparent/glass, glossy, matte)")
    patterns: List[str] = Field(default_factory=list, description="Visual patterns (stripes, camo, plaid, solid, printed)")
    distinctive_features: List[str] = Field(default_factory=list, description="Specific identifying marks (stickers, keychains, scratches, cracks, broken zippers, logos, charms)")
    confidence_scores: Dict[str, Any] = Field(default_factory=dict, description="Estimated confidence score [0.0 - 1.0] per recognized attribute or metadata")


class TaxonomyResponse(BaseModel):
    """Standardized taxonomy of supported physical and visual categories and traits."""
    categories: List[str]
    shapes: List[str]
    primary_colors: List[str]
    sizes: List[str]
    materials: List[str]
    common_distinctive_features: List[str]


class AttributeExtractionRequest(BaseModel):
    """Request to extract attributes from textual description and metadata."""
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    category: Optional[str] = Field(default=None, max_length=80)
    color: Optional[str] = Field(default=None, max_length=50)


class AttributeExtractionResponse(BaseModel):
    """Recognized attributes and human-readable summary."""
    attributes: ItemAttributes
    summary: str


class MatchExplanation(BaseModel):
    """Explainable reasoning detailing why two reports were matched."""
    summary: str = Field(..., description="Top-line summary of match evidence")
    reasons: List[str] = Field(default_factory=list, description="Bullet reasons outlining agreeing signals")
    shared_distinctive_features: List[str] = Field(default_factory=list, description="High-specificity features shared between items")
    attribute_breakdown: Dict[str, str] = Field(default_factory=dict, description="Detailed comparison per attribute dimension")
    confidence_calibration_note: str = Field(..., description="Transparent, uncalibrated uncertainty and verification notice")


class AttributeMatchItem(BaseModel):
    """Ranked report candidate with attribute breakdown and match explanations."""
    report_id: int
    item_name: str
    category: str
    report_type: str
    location_text: str
    event_date: Optional[str] = None
    description: str
    color: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    match_score: float = Field(..., description="Composite match score in [0.0, 100.0]")
    visual_score: Optional[float] = Field(default=None, description="CLIP visual embedding similarity in [0.0, 100.0]")
    text_score: Optional[float] = Field(default=None, description="CLIP/lexical text embedding similarity in [0.0, 100.0]")
    attribute_score: Optional[float] = Field(default=None, description="Attribute agreement score in [0.0, 100.0]")
    attributes: ItemAttributes
    explanation: MatchExplanation
    best_image_url: Optional[str] = None
    candidate_image_count: int = 0


class AttributeFilterRequest(BaseModel):
    """Flexible attribute-filtered search request."""
    query_text: Optional[str] = Field(default=None, description="Free text or natural language description")
    category: Optional[str] = Field(default=None, description="Object category filter")
    primary_color: Optional[str] = Field(default=None, description="Primary color")
    secondary_color: Optional[str] = Field(default=None, description="Secondary or accent color")
    shape: Optional[str] = Field(default=None, description="Shape filter")
    size_category: Optional[str] = Field(default=None, description="Size category (small, medium, large)")
    min_capacity_litres: Optional[float] = Field(default=None, ge=0.0)
    max_capacity_litres: Optional[float] = Field(default=None, ge=0.0)
    material: Optional[str] = Field(default=None, description="Material/texture filter")
    distinctive_features: Optional[str] = Field(default=None, description="Distinctive feature terms (e.g. 'red keychain', 'sticker')")
    location_text: Optional[str] = Field(default=None, description="Location search term")
    target_type: Optional[str] = Field(default=None, description="'lost', 'found', or None for all active reports")
    hard_filters: List[str] = Field(default_factory=list, description="List of attributes that MUST strictly match (others act as soft rank boosters)")
    min_score: float = Field(default=30.0, ge=0.0, le=100.0, description="Minimum match score required to be returned")
    limit: int = Field(default=20, ge=1, le=100)


class AttributeSearchResponse(BaseModel):
    """Result of an attribute-aware multi-modal search."""
    query_attributes: ItemAttributes
    query_image_count: int = 0
    candidate_count: int = 0
    matches: List[AttributeMatchItem] = Field(default_factory=list)
