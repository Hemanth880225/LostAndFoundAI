"""Attribute extraction engine combining linguistic heuristics and CLIP zero-shot vision."""

import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image, UnidentifiedImageError

from app.extensions.attribute_matching.schemas import ItemAttributes

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TAXONOMY DEFINITIONS
# ---------------------------------------------------------------------------

TAXONOMY_CATEGORIES = [
    "Backpack", "Handbag", "Suitcase", "Duffel Bag", "Tote Bag",
    "Water Bottle", "Smartphone", "Laptop", "Tablet", "Wallet",
    "Umbrella", "Keys", "Earphones", "Headphones", "Watch",
    "Glasses", "Lunchbox", "Book", "Charger", "Clothing", "Other",
]

TAXONOMY_SHAPES = [
    "Rectangular", "Circular", "Oval", "Cylindrical", "Square", "Rounded", "Irregular",
]

TAXONOMY_PRIMARY_COLORS = [
    "Black", "White", "Silver", "Grey", "Blue", "Navy Blue", "Red",
    "Green", "Yellow", "Brown", "Pink", "Purple", "Orange", "Gold",
    "Maroon", "Beige", "Olive",
]

TAXONOMY_SIZES = [
    "Small", "Medium", "Large", "Compact", "Oversized",
]

TAXONOMY_MATERIALS = [
    "Leather-like", "Fabric/Canvas", "Plastic", "Metal",
    "Transparent/Glass", "Glossy", "Matte", "Rubber/Silicone",
]

TAXONOMY_DISTINCTIVE_KEYWORDS = [
    "keychain", "key ring", "sticker", "decal", "scratch", "cracked",
    "broken", "initials", "engraving", "engraved", "logo", "charm",
    "lanyard", "popsocket", "patch", "zipper pocket", "padded strap",
    "carabiner", "tag", "embroidery",
]

# Objects where volume/capacity is genuinely meaningful
CAPACITY_ELIGIBLE_CATEGORIES = {
    "backpack", "bag", "duffel bag", "tote bag", "suitcase", "luggage",
    "water bottle", "bottle", "flask", "tumbler", "container", "lunchbox",
    "storage", "hard drive", "pen drive",
}


# ---------------------------------------------------------------------------
# COLOR CLUSTER PALETTE FOR PIL PIXEL ANALYSIS
# ---------------------------------------------------------------------------

COLOR_REFERENCE_PALETTE: Dict[str, Tuple[int, int, int]] = {
    "Black": (20, 20, 20),
    "White": (240, 240, 240),
    "Grey": (128, 128, 128),
    "Silver": (192, 192, 192),
    "Red": (200, 30, 30),
    "Maroon": (128, 0, 0),
    "Blue": (30, 80, 200),
    "Navy Blue": (15, 30, 90),
    "Green": (30, 150, 50),
    "Olive": (100, 110, 40),
    "Yellow": (230, 210, 30),
    "Gold": (212, 175, 55),
    "Orange": (235, 120, 20),
    "Brown": (120, 70, 30),
    "Pink": (230, 130, 170),
    "Purple": (130, 40, 160),
    "Beige": (225, 210, 180),
}


def _rgb_distance(c1: Tuple[int, int, int], c2: Tuple[int, int, int]) -> float:
    """Euclidean distance in RGB color space."""
    return ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2 + (c1[2] - c2[2]) ** 2) ** 0.5


def _map_rgb_to_color_name(rgb: Tuple[int, int, int]) -> str:
    """Find closest canonical color name for an RGB triple."""
    closest_color = "Black"
    min_dist = float("inf")
    for name, ref_rgb in COLOR_REFERENCE_PALETTE.items():
        dist = _rgb_distance(rgb, ref_rgb)
        if dist < min_dist:
            min_dist = dist
            closest_color = name
    return closest_color


# ---------------------------------------------------------------------------
# TEXT-BASED ATTRIBUTE EXTRACTION
# ---------------------------------------------------------------------------

def extract_attributes_from_text(
    title: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    color: Optional[str] = None,
) -> ItemAttributes:
    """
    Extract multi-dimensional attributes from report title, description, and metadata.
    Enforces the rule that uncertain or absent attributes remain None instead of inventing values.
    """
    raw_text = f"{title or ''} {description or ''} {color or ''}".strip()
    lower_text = raw_text.lower()

    scores: Dict[str, float] = {}

    # 1. Category
    inferred_category = None
    if category and category.strip():
        inferred_category = category.strip().title()
        scores["category"] = 0.95
    else:
        for cat in TAXONOMY_CATEGORIES:
            if re.search(rf"\b{re.escape(cat.lower())}\b", lower_text):
                inferred_category = cat
                scores["category"] = 0.85
                break

    # 2. Colors: Primary, Secondary, and Multicolor
    # 2. Colors: Primary, Secondary, and Multicolor
    primary_color = None
    secondary_color = None
    is_multicolor = False

    # Collect all taxonomy colors present in text with their positions
    color_occurrences: List[Tuple[int, str]] = []
    for c in sorted(TAXONOMY_PRIMARY_COLORS, key=len, reverse=True):
        c_low = c.lower()
        for m in re.finditer(rf"\b{re.escape(c_low)}\b", lower_text):
            start = m.start()
            if not any(abs(start - existing_start) < len(c_low) for existing_start, _ in color_occurrences):
                color_occurrences.append((start, c))
    for alias, canonical in [("gray", "Grey"), ("golden", "Gold")]:
        for m in re.finditer(rf"\b{alias}\b", lower_text):
            start = m.start()
            if not any(abs(start - existing_start) < 4 for existing_start, _ in color_occurrences):
                color_occurrences.append((start, canonical))

    color_occurrences.sort(key=lambda x: x[0])

    # Check for explicit accent indicators: e.g. "white accents", "grey trim", "red stripes"
    accent_color = None
    for _, c in color_occurrences:
        if re.search(rf"\b{re.escape(c.lower())}\s*(?:accents?|stripes?|trim|details?|lining|strap|highlights?)\b", lower_text):
            accent_color = c
            break

    if color and color.strip():
        # User explicitly specified a color field
        for c in TAXONOMY_PRIMARY_COLORS:
            if c.lower() == color.strip().lower() or c.lower() in color.strip().lower():
                primary_color = c
                break

    if not primary_color and color_occurrences:
        if accent_color:
            secondary_color = accent_color
            other_colors = [c for _, c in color_occurrences if c != accent_color]
            if other_colors:
                primary_color = other_colors[0]
            else:
                primary_color = accent_color
                secondary_color = None
        else:
            primary_color = color_occurrences[0][1]
            distinct_others = [c for _, c in color_occurrences[1:] if c != primary_color]
            if distinct_others:
                secondary_color = distinct_others[0]
    elif primary_color and not secondary_color and color_occurrences:
        distinct_others = [c for _, c in color_occurrences if c != primary_color]
        if distinct_others:
            secondary_color = distinct_others[0]

    if any(m in lower_text for m in ["multicolor", "multi-color", "rainbow", "two-tone", "patterned", "plaid", "camo"]):
        is_multicolor = True

    if primary_color:
        scores["primary_color"] = 0.90
    if secondary_color:
        scores["secondary_color"] = 0.80

    # 3. Shape
    shape = None
    shape_patterns = {
        "Rectangular": [r"\brectang(?:le|ular)\b", r"\bbar\b", r"\bbox\b"],
        "Circular": [r"\bcircular\b", r"\bround\b", r"\bdisc\b", r"\bcircle\b"],
        "Oval": [r"\boval\b", r"\belliptical\b"],
        "Cylindrical": [r"\bcylind(?:er|rical)\b", r"\btube\b", r"\btubular\b", r"\bflask\b"],
        "Square": [r"\bsquare\b", r"\bcubic\b"],
        "Rounded": [r"\brounded corners?\b", r"\brounded\b"],
        "Irregular": [r"\birregular\b", r"\basymmetric(?:al)?\b"],
    }

    for s_name, pats in shape_patterns.items():
        if any(re.search(pat, lower_text) for pat in pats):
            shape = s_name
            scores["shape"] = 0.85
            break

    # Implied default shape for specific object categories when not explicitly stated
    if not shape and inferred_category:
        cat_lower = inferred_category.lower()
        if "bottle" in cat_lower or "flask" in cat_lower:
            shape = "Cylindrical"
            scores["shape"] = 0.70
        elif any(k in cat_lower for k in ["backpack", "book", "laptop", "tablet", "wallet", "phone"]):
            shape = "Rectangular"
            scores["shape"] = 0.70

    # 4. Size Category & Dimensions
    size_category = None
    dimensions_text = None

    if any(re.search(rf"\b{w}\b", lower_text) for w in ["small", "compact", "mini", "pocket-sized", "pocket size", "little"]):
        size_category = "Small"
        scores["size_category"] = 0.85
    elif any(re.search(rf"\b{w}\b", lower_text) for w in ["large", "big", "oversized", "bulky", "huge"]):
        size_category = "Large"
        scores["size_category"] = 0.85
    elif any(re.search(rf"\b{w}\b", lower_text) for w in ["medium", "standard size", "mid-sized", "mid size"]):
        size_category = "Medium"
        scores["size_category"] = 0.85

    dim_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:-?\s*inch|\"|in\b|cm\b|x\s*\d+)", lower_text)
    if dim_match:
        full_match = re.search(r"\b\d+(?:\.\d+)?\s*(?:x\s*\d+(?:\.\d+)?\s*(?:x\s*\d+(?:\.\d+)?)?\s*cm|\-?\s*inch|\")\b", lower_text)
        dimensions_text = full_match.group(0) if full_match else dim_match.group(0)
        scores["dimensions_text"] = 0.90

    # 5. Capacity (strictly applicable to containers, bags, bottles, or digital storage)
    capacity_litres = None
    capacity_text = None

    cat_check = (inferred_category or "").lower()
    is_capacity_eligible = not inferred_category or any(k in cat_check for k in CAPACITY_ELIGIBLE_CATEGORIES) or any(k in lower_text for k in ["litre", "liter", "bottle", "bag", "backpack", "flask", "ml"])

    if is_capacity_eligible:
        # Range in litres: "20-30 litres", "20 to 30L"
        range_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)\s*(?:l|litres?|liters?)\b", lower_text)
        if range_match:
            v1, v2 = float(range_match.group(1)), float(range_match.group(2))
            capacity_litres = round((v1 + v2) / 2.0, 1)
            capacity_text = f"{range_match.group(1)}–{range_match.group(2)} litres"
            scores["capacity_litres"] = 0.90

        if capacity_litres is None:
            # Single value in litres: "25L", "25 litres"
            single_l_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:l|litres?|liters?)\b", lower_text)
            if single_l_match:
                capacity_litres = float(single_l_match.group(1))
                capacity_text = f"{single_l_match.group(1)}L"
                scores["capacity_litres"] = 0.90

        if capacity_litres is None:
            # Value in millilitres: "750ml", "500 ml"
            ml_match = re.search(r"\b(\d+)\s*(?:ml|millilitres?|milliliters?)\b", lower_text)
            if ml_match:
                ml_val = float(ml_match.group(1))
                capacity_litres = round(ml_val / 1000.0, 2)
                capacity_text = f"{ml_match.group(1)}ml"
                scores["capacity_litres"] = 0.90

        if capacity_litres is None:
            # Digital storage: "128GB", "1TB"
            storage_match = re.search(r"\b(\d+)\s*(gb|tb)\b", lower_text)
            if storage_match:
                capacity_text = f"{storage_match.group(1)}{storage_match.group(2).upper()}"
                scores["capacity_litres"] = 0.85

    # 6. Material and Texture
    material = None
    mat_patterns = {
        "Leather-like": [r"\bleather\b", r"\bleatherette\b", r"\bfaux leather\b"],
        "Fabric/Canvas": [r"\bfabric\b", r"\bcanvas\b", r"\bnylon\b", r"\bpolyester\b", r"\bcloth\b", r"\bdenim\b"],
        "Plastic": [r"\bplastic\b", r"\bpolycarbonate\b", r"\bacrylic\b"],
        "Metal": [r"\bmetal\b", r"\bmetall?ic\b", r"\baluminum\b", r"\baluminium\b", r"\bsteel\b", r"\bstainless(?:\s+steel)?\b", r"\bbrass\b", r"\bcopper\b", r"\btitanium\b"],
        "Transparent/Glass": [r"\btransparent\b", r"\bclear glass\b", r"\bglass\b", r"\bsee-through\b"],
        "Glossy": [r"\bglossy\b", r"\bshiny\b"],
        "Matte": [r"\bmatte\b", r"\bnon-reflective\b"],
        "Rubber/Silicone": [r"\brubber\b", r"\bsilicone\b"],
    }
    earliest_pos = float("inf")
    for m_name, pats in mat_patterns.items():
        for pat in pats:
            m = re.search(pat, lower_text)
            if m and m.start() < earliest_pos:
                earliest_pos = m.start()
                material = m_name
                scores["material"] = 0.85

    # 7. Patterns
    patterns = []
    if re.search(r"\bstrip(?:es?|ed)\b", lower_text):
        patterns.append("Striped")
    if re.search(r"\b(?:camo|camouflag(?:e|ed))\b", lower_text):
        patterns.append("Camouflage")
    if re.search(r"\b(?:plaid|checkered|checks?)\b", lower_text):
        patterns.append("Plaid/Checkered")
    if re.search(r"\bpolka dots?\b", lower_text):
        patterns.append("Polka dot")
    if re.search(r"\bfloral\b", lower_text):
        patterns.append("Floral")
    if re.search(r"\bsolid\s+color\b", lower_text):
        patterns.append("Solid")

    # 8. Distinctive Features
    distinctive_features = []
    # Keychains and charms
    keychain_match = re.search(r"\b([a-z0-9\-]+\s+(?:keychain|key ring|charm|lanyard|tag))\b", lower_text)
    if keychain_match:
        distinctive_features.append(keychain_match.group(1).strip().capitalize())
    elif re.search(r"\bkeychain\b", lower_text):
        distinctive_features.append("Keychain")

    # Stickers and decals
    sticker_match = re.search(r"\b([a-z0-9\-]+\s+(?:sticker|decal))\b", lower_text)
    if sticker_match:
        distinctive_features.append(sticker_match.group(1).strip().capitalize())
    elif re.search(r"\bstickers?\b", lower_text):
        distinctive_features.append("Sticker")

    # Physical marks, damages, or engravings
    mark_match = re.search(r"\b((?:scratched|cracked|broken|dented|torn)\s+[a-z]+)\b", lower_text)
    if mark_match:
        distinctive_features.append(mark_match.group(1).strip().capitalize())

    # Initials or monograms
    initials_match = re.search(r"\b(?:initials?|monogram|engraved?)\s*(?:of|with|:)?\s*([A-Za-z0-9&.\-]{1,6})\b", raw_text)
    if initials_match:
        distinctive_features.append(f"Initials {initials_match.group(1).strip().upper()}")

    # Distinctive hardware (zippers, pockets, straps)
    if re.search(r"\bfront zipper pocket\b", lower_text):
        distinctive_features.append("Front zipper pocket")
    if re.search(r"\bpadded straps?\b", lower_text):
        distinctive_features.append("Padded straps")

    if distinctive_features:
        scores["distinctive_features"] = 0.95

    return ItemAttributes(
        category=inferred_category,
        primary_color=primary_color,
        secondary_color=secondary_color,
        is_multicolor=is_multicolor,
        shape=shape,
        size_category=size_category,
        dimensions_text=dimensions_text,
        capacity_litres=capacity_litres,
        capacity_text=capacity_text,
        material=material,
        patterns=patterns,
        distinctive_features=list(dict.fromkeys(distinctive_features)),
        confidence_scores=scores,
    )


# ---------------------------------------------------------------------------
# VISION-BASED ATTRIBUTE EXTRACTION
# ---------------------------------------------------------------------------

def extract_attributes_from_image(
    image_source: Union[str, Path, BytesIO, bytes, Image.Image]
) -> ItemAttributes:
    """
    Extract visual attributes directly from an image.
    Uses PIL color clustering for dominant color and CLIP zero-shot classification for shapes/materials/categories.
    Fails gracefully without raising exceptions if CLIP or image processing fails.
    """
    # 1. Load image safely into PIL RGB format
    try:
        if isinstance(image_source, Image.Image):
            img = image_source.convert("RGB")
        elif isinstance(image_source, (bytes, bytearray)):
            with Image.open(BytesIO(image_source)) as opened:
                opened.load()
                img = opened.convert("RGB")
        elif isinstance(image_source, BytesIO):
            with Image.open(image_source) as opened:
                opened.load()
                img = opened.convert("RGB")
        elif isinstance(image_source, (str, Path)):
            with Image.open(Path(image_source)) as opened:
                opened.load()
                img = opened.convert("RGB")
        else:
            return ItemAttributes()
    except Exception as exc:
        logger.warning(f"Could not load image for attribute extraction: {exc}")
        return ItemAttributes()

    scores: Dict[str, float] = {}

    # 2. Extract Dominant Color Clusters via PIL
    primary_color, secondary_color, is_multicolor = _extract_image_colors(img)
    if primary_color:
        scores["primary_color"] = 0.85
    if secondary_color:
        scores["secondary_color"] = 0.70

    # 3. CLIP Zero-Shot Classification
    category = None
    shape = None
    material = None
    size_category = None

    try:
        from app.ai.clip_model import get_clip_components
        processor, model, device = get_clip_components()

        # Categories
        cat_prompts = [f"a photo of a {c.lower()}" for c in TAXONOMY_CATEGORIES]
        cat_res = _run_clip_zeroshot(img, cat_prompts, processor, model, device)
        if cat_res and cat_res[1] >= 0.28:
            category = TAXONOMY_CATEGORIES[cat_res[0]]
            scores["category"] = round(cat_res[1], 2)

        # Shapes
        shape_prompts = [
            "a rectangular shaped object",
            "a circular or round object",
            "an oval shaped object",
            "a cylindrical shaped object or bottle",
            "a square shaped object",
            "a rounded object",
            "an irregular or complex shaped object",
        ]
        shape_res = _run_clip_zeroshot(img, shape_prompts, processor, model, device)
        if shape_res and shape_res[1] >= 0.26:
            shape = TAXONOMY_SHAPES[shape_res[0]]
            scores["shape"] = round(shape_res[1], 2)

        # Materials
        mat_prompts = [
            "an object made of leather or leatherette",
            "an object made of fabric, canvas or nylon",
            "an object made of plastic",
            "an object made of metal or aluminum",
            "an object made of transparent glass or plastic",
            "an object with a glossy shiny surface",
            "an object with a matte surface",
            "an object made of rubber or silicone",
        ]
        mat_res = _run_clip_zeroshot(img, mat_prompts, processor, model, device)
        if mat_res and mat_res[1] >= 0.28:
            material = TAXONOMY_MATERIALS[mat_res[0]]
            scores["material"] = round(mat_res[1], 2)

        # Size category
        size_prompts = [
            "a small, pocket-sized or handheld object",
            "a medium-sized everyday object",
            "a large, bulky or heavy object",
        ]
        size_res = _run_clip_zeroshot(img, size_prompts, processor, model, device)
        if size_res and size_res[1] >= 0.35:
            size_category = ["Small", "Medium", "Large"][size_res[0]]
            scores["size_category"] = round(size_res[1], 2)

    except Exception as exc:
        logger.debug(f"CLIP zero-shot inference unavailable or skipped: {exc}")

    return ItemAttributes(
        category=category,
        primary_color=primary_color,
        secondary_color=secondary_color,
        is_multicolor=is_multicolor,
        shape=shape,
        size_category=size_category,
        material=material,
        confidence_scores=scores,
    )


def _extract_image_colors(img: Image.Image) -> Tuple[Optional[str], Optional[str], bool]:
    """Analyze pixel distribution to extract primary and secondary colors."""
    try:
        small = img.resize((64, 64)).convert("RGB")
        quantized = small.quantize(colors=6, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette()
        if not palette:
            return None, None, False

        color_counts = quantized.getcolors()
        if not color_counts:
            return None, None, False

        # Sort by pixel frequency descending
        color_counts.sort(key=lambda x: x[0], reverse=True)
        total_pixels = sum(count for count, _ in color_counts)

        color_names_with_weights = []
        for count, idx in color_counts:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            c_name = _map_rgb_to_color_name((r, g, b))
            color_names_with_weights.append((c_name, count / total_pixels))

        # Aggregate weights per canonical color name
        aggregated: Dict[str, float] = {}
        for c_name, weight in color_names_with_weights:
            aggregated[c_name] = aggregated.get(c_name, 0.0) + weight

        sorted_colors = sorted(aggregated.items(), key=lambda x: x[1], reverse=True)

        primary = sorted_colors[0][0] if sorted_colors else None
        secondary = None
        if len(sorted_colors) > 1 and sorted_colors[1][1] >= 0.18 and sorted_colors[1][0] != primary:
            secondary = sorted_colors[1][0]

        is_multi = len([c for c, w in sorted_colors if w >= 0.15]) >= 3

        return primary, secondary, is_multi
    except Exception:
        return None, None, False


def _run_clip_zeroshot(
    img: Image.Image,
    prompts: List[str],
    processor: Any,
    model: Any,
    device: str,
) -> Optional[Tuple[int, float]]:
    """Run CLIP forward pass against candidate text prompts and return top index & probability."""
    import torch
    import torch.nn.functional as F

    inputs = processor(
        text=prompts,
        images=img,
        return_tensors="pt",
        padding=True,
    )
    inputs = {k: v.to(device) for k, v in inputs.items()}

    with torch.no_grad():
        outputs = model(**inputs)
        logits = outputs.logits_per_image[0]
        probs = F.softmax(logits, dim=0).cpu().tolist()

    max_prob = max(probs)
    max_idx = probs.index(max_prob)
    return max_idx, max_prob


# ---------------------------------------------------------------------------
# MERGE ATTRIBUTES
# ---------------------------------------------------------------------------

def merge_attributes(
    text_attrs: ItemAttributes,
    image_attrs: Optional[ItemAttributes] = None,
) -> ItemAttributes:
    """
    Intelligently merge text-derived and vision-derived attributes.
    Explicit textual statements take priority; vision corroborates and fills missing dimensions.
    """
    if not image_attrs:
        return text_attrs

    merged_scores = dict(text_attrs.confidence_scores)

    # Category: Text preferred, vision fallback
    cat = text_attrs.category or image_attrs.category
    if not text_attrs.category and image_attrs.category:
        merged_scores["category"] = image_attrs.confidence_scores.get("category", 0.70)

    # Primary Color: Text preferred, vision fallback
    p_color = text_attrs.primary_color or image_attrs.primary_color
    if not text_attrs.primary_color and image_attrs.primary_color:
        merged_scores["primary_color"] = image_attrs.confidence_scores.get("primary_color", 0.70)

    # Secondary Color
    s_color = text_attrs.secondary_color or image_attrs.secondary_color

    # Multicolor
    is_multi = text_attrs.is_multicolor or image_attrs.is_multicolor

    # Shape: Text preferred, vision fallback
    shape = text_attrs.shape or image_attrs.shape
    if not text_attrs.shape and image_attrs.shape:
        merged_scores["shape"] = image_attrs.confidence_scores.get("shape", 0.70)

    # Size category
    size_cat = text_attrs.size_category or image_attrs.size_category

    # Material
    material = text_attrs.material or image_attrs.material
    if not text_attrs.material and image_attrs.material:
        merged_scores["material"] = image_attrs.confidence_scores.get("material", 0.70)

    return ItemAttributes(
        category=cat,
        primary_color=p_color,
        secondary_color=s_color,
        is_multicolor=is_multi,
        shape=shape,
        size_category=size_cat,
        dimensions_text=text_attrs.dimensions_text,
        capacity_litres=text_attrs.capacity_litres,
        capacity_text=text_attrs.capacity_text,
        material=material,
        patterns=list(dict.fromkeys(text_attrs.patterns + image_attrs.patterns)),
        distinctive_features=text_attrs.distinctive_features,
        confidence_scores=merged_scores,
    )
