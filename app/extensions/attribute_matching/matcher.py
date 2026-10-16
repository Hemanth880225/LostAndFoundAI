"""Attribute-aware comparison engine, distinctive feature weighting, and explainability generator."""

import difflib
from typing import Any, Dict, List, Optional, Tuple

from app.extensions.attribute_matching.schemas import ItemAttributes, MatchExplanation


import re

# ---------------------------------------------------------------------------
# OBJECT CATEGORY TAXONOMY & COMPATIBILITY ONTOLOGY
# ---------------------------------------------------------------------------

# Canonical physical object types and their defining regex patterns
OBJECT_TYPE_PATTERNS = [
    ("audio.neckband", [r"\bneckband\b", r"\bneck\s*band\b", r"\bwireless\s*neckband\b", r"\bbluetooth\s*neckband\b"]),
    ("audio.earbuds", [r"\bearbuds?\b", r"\bairpods?\b", r"\btws\b", r"\bin-ear\s*buds?\b", r"\bwireless\s*earbuds?\b", r"\btws\s*earbuds?\b", r"\bin-ear\b", r"\bearphones?\b"]),
    ("audio.over_ear", [r"\bheadphones?\b", r"\bover-ear\b", r"\bon-ear\b", r"\bheadset\b", r"\bstudio\s*headphones?\b"]),
    ("audio.wired", [r"\bwired\s*earphones?\b", r"\bwired\s*headphones?\b", r"\b3\.5mm\b"]),
    
    ("power.charger", [r"\bchargers?\b", r"\bwall\s*charger\b", r"\bpower\s*adapters?\b", r"\badapters?\b", r"\bcharging\s*brick\b"]),
    ("power.cable", [r"\bcables?\b", r"\bcharging\s*cable\b", r"\busb\s*cable\b", r"\btype-c\s*cable\b", r"\blightning\s*cable\b", r"\bcord\b"]),
    ("power.bank", [r"\bpower\s*bank\b", r"\bportable\s*battery\b"]),
    
    ("computing.laptop", [r"\blaptops?\b", r"\bnotebooks?\b", r"\bmacbooks?\b", r"\bchromebooks?\b", r"\bultrabooks?\b"]),
    ("computing.tablet", [r"\btablets?\b", r"\bipads?\b", r"\btabs?\b"]),
    ("computing.phone", [r"\bsmartphones?\d*\b", r"\bphones?\d*\b", r"\bmobiles?\b", r"\biphones?\d*\b", r"\bcell\s*phones?\b", r"\bandroid\b", r"\bnothing\s*phone\b"]),
    
    ("bags.backpack", [r"\bbackpacks?\b", r"\bbags?\b", r"\brucksacks?\b", r"\bknapsacks?\b", r"\bdaypacks?\b", r"\bschool\s*bags?\b", r"\bcollege\s*bags?\b"]),
    ("bags.handbag", [r"\bhandbags?\b", r"\bpurses?\b", r"\btote\s*bags?\b", r"\bshoulder\s*bags?\b", r"\bsatchels?\b"]),
    ("bags.duffel", [r"\bduffel\s*bags?\b", r"\bduffels?\b", r"\bgym\s*bags?\b", r"\bsports\s*bags?\b"]),
    ("bags.suitcase", [r"\bsuitcases?\b", r"\bluggages?\b", r"\btrolleys?\b", r"\btravel\s*bags?\b"]),
    
    ("eyewear.glasses", [r"\bglasses\b", r"\beyeglasses\b", r"\bspectacles\b", r"\bsunglasses\b", r"\bframes?\b"]),
    ("drinkware.bottle", [r"\bwater\s*bottles?\b", r"\bbottles?\b", r"\bflasks?\b", r"\btumblers?\b", r"\bthermos\b", r"\bsippers?\b"]),
    ("drinkware.lunchbox", [r"\blunchbox(?:es)?\b", r"\blunch\s*box\b", r"\btiffins?\b", r"\bfood\s*containers?\b"]),
    
    ("stationery.book", [r"\bbooks?\b", r"\bnotebooks?\b", r"\blongbooks?\b", r"\btextbooks?\b", r"\bdiaries\b", r"\bdiary\b", r"\bbinders?\b"]),
    ("personal.wallet", [r"\bwallets?\b", r"\bbillfolds?\b", r"\bcardholders?\b", r"\bcard\s*holders?\b"]),
    ("personal.watch", [r"\bwatch(?:es)?\b", r"\bsmartwatch(?:es)?\b", r"\bwrist\s*watch\b"]),
    ("personal.umbrella", [r"\bumbrellas?\b"]),
    ("personal.keys", [r"\bkeys?\b", r"\bkeychains?\b", r"\bkey\s*rings?\b"]),
]

BROAD_CATEGORIES: Dict[str, set[str]] = {
    "electronics": {"audio", "power", "computing"},
    "gadgets": {"audio", "power", "computing"},
    "bags": {"bags"},
    "accessories": {"personal", "eyewear"},
}

CATEGORY_SYNONYMS: Dict[str, set[str]] = {
    "backpack": {"bag", "rucksack", "knapsack", "daypack"},
    "handbag": {"bag", "purse", "tote bag", "shoulder bag"},
    "suitcase": {"luggage", "trolley", "travel bag"},
    "duffel bag": {"bag", "gym bag", "sports bag"},
    "water bottle": {"bottle", "flask", "tumbler", "thermos", "sipper"},
    "smartphone": {"phone", "mobile", "cell phone"},
    "laptop": {"notebook", "macbook", "computer"},
    "tablet": {"ipad", "tab"},
    "wallet": {"purse", "cardholder", "billfold"},
    "earphones": {"headphones", "airpods", "earbuds", "headset"},
    "headphones": {"earphones", "headset"},
}

# Related shapes with partial geometric resemblance
SHAPE_SIMILARITY = {
    ("rectangular", "square"): 0.75,
    ("square", "rectangular"): 0.75,
    ("circular", "rounded"): 0.85,
    ("rounded", "circular"): 0.85,
    ("circular", "oval"): 0.80,
    ("oval", "circular"): 0.80,
    ("cylindrical", "circular"): 0.65,
    ("circular", "cylindrical"): 0.65,
}

# Related colors with shade or family proximity
COLOR_SIMILARITY = {
    ("grey", "silver"): 0.85,
    ("silver", "grey"): 0.85,
    ("blue", "navy blue"): 0.90,
    ("navy blue", "blue"): 0.90,
    ("red", "maroon"): 0.75,
    ("maroon", "red"): 0.75,
    ("yellow", "gold"): 0.80,
    ("gold", "yellow"): 0.80,
    ("brown", "beige"): 0.70,
    ("beige", "brown"): 0.70,
}


def resolve_canonical_object_type(
    category: Optional[str] = None,
    item_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Infer canonical physical object type (e.g. 'audio.earbuds', 'bags.backpack')
    from structured category and text context.
    """
    corpus = f"{category or ''} {item_name or ''} {description or ''}".lower()
    
    for obj_type, patterns in OBJECT_TYPE_PATTERNS:
        if any(re.search(pat, corpus) for pat in patterns):
            return obj_type
            
    cat_lower = (category or "").lower().strip()
    if cat_lower in ("earphones", "earbuds"):
        return "audio.earbuds"
    if cat_lower == "neckband":
        return "audio.neckband"
    if cat_lower == "headphones":
        return "audio.over_ear"
    if cat_lower == "charger":
        return "power.charger"
    if cat_lower in ("backpack", "bag", "bags"):
        return "bags.backpack"
    if cat_lower == "laptop":
        return "computing.laptop"
    if cat_lower == "glasses":
        return "eyewear.glasses"
    if cat_lower == "book":
        return "stationery.book"
    if cat_lower in ("bottle", "water bottle"):
        return "drinkware.bottle"
    if cat_lower in ("phone", "smartphone"):
        return "computing.phone"
    if cat_lower == "wallet":
        return "personal.wallet"
    if cat_lower == "watch":
        return "personal.watch"
    if cat_lower == "umbrella":
        return "personal.umbrella"
        
    return "unknown"


def compute_category_compatibility(
    type_a: str,
    type_b: str,
    raw_cat_a: Optional[str] = None,
    raw_cat_b: Optional[str] = None,
) -> Tuple[float, str, str]:
    """
    Principled 4-tier category compatibility evaluation:
    Returns (compatibility_score [0.0 - 1.0], tier_name, explanation_text)
    Tiers:
      - 'exact': 1.0 (Same physical object type)
      - 'related': 0.30 - 0.55 (Same functional family, distinct physical form factor)
      - 'broad': 0.70 (Broad umbrella category match)
      - 'incompatible': 0.0 (Unrelated object types)
      - 'unknown': 0.65 (Category insufficiently specified on one or both sides)
    """
    if type_a == "unknown" or type_b == "unknown":
        raw_a = (raw_cat_a or "").lower().strip()
        raw_b = (raw_cat_b or "").lower().strip()
        if raw_a and raw_b:
            if raw_a == raw_b:
                return 1.0, "exact", f"Matching category ({raw_cat_a})"
            for broad, fams in BROAD_CATEGORIES.items():
                if raw_a == broad or raw_b == broad:
                    return 0.70, "broad", f"Broad category match ({broad.title()})"
        return 0.65, "unknown", "Category unspecified or general"
        
    if type_a == type_b:
        display_name = type_a.split(".")[-1].replace("_", " ").title()
        return 1.0, "exact", f"Matching category ({display_name})"
        
    fam_a, sub_a = type_a.split(".", 1)
    fam_b, sub_b = type_b.split(".", 1)
    
    # Same family, different form factor
    if fam_a == fam_b:
        if fam_a == "audio":
            if (sub_a == "earbuds" and sub_b == "neckband") or (sub_a == "neckband" and sub_b == "earbuds"):
                return 0.40, "related", "Related audio category (Earbuds vs Neckband earphones)"
            if (sub_a == "earbuds" and sub_b == "over_ear") or (sub_a == "over_ear" and sub_b == "earbuds"):
                return 0.30, "related", "Related audio category (Earbuds vs Over-ear headphones)"
            if (sub_a == "neckband" and sub_b == "over_ear") or (sub_a == "over_ear" and sub_b == "neckband"):
                return 0.35, "related", "Related audio category (Neckband vs Over-ear headphones)"
            return 0.50, "related", "Related audio equipment"
            
        elif fam_a == "bags":
            if (sub_a == "backpack" and sub_b == "duffel") or (sub_a == "duffel" and sub_b == "backpack"):
                return 0.55, "related", "Related bag category (Backpack vs Duffel bag)"
            if (sub_a == "backpack" and sub_b == "handbag") or (sub_a == "handbag" and sub_b == "backpack"):
                return 0.45, "related", "Related bag category (Backpack vs Handbag)"
            if (sub_a == "backpack" and sub_b == "suitcase") or (sub_a == "suitcase" and sub_b == "backpack"):
                return 0.40, "related", "Related travel luggage (Backpack vs Suitcase)"
            return 0.50, "related", "Related bag category"
            
        elif fam_a == "power":
            if (sub_a == "charger" and sub_b == "cable") or (sub_a == "cable" and sub_b == "charger"):
                return 0.50, "related", "Related charging accessory (Charger vs Cable)"
            if (sub_a == "charger" and sub_b == "bank") or (sub_a == "bank" and sub_b == "charger"):
                return 0.55, "related", "Related power accessory (Charger vs Power bank)"
            return 0.50, "related", "Related power accessory"
            
        elif fam_a == "computing":
            if (sub_a == "laptop" and sub_b == "tablet") or (sub_a == "tablet" and sub_b == "laptop"):
                return 0.50, "related", "Related computing device (Laptop vs Tablet)"
            if (sub_a == "phone" and sub_b == "tablet") or (sub_a == "tablet" and sub_b == "phone"):
                return 0.50, "related", "Related mobile device (Phone vs Tablet)"
            return 0.35, "related", "Related computing device"
            
        return 0.50, "related", f"Related {fam_a.title()} items"
        
    # Distinct object families (e.g. Audio vs Computing, Audio vs Power, Bags vs Audio) are incompatible
    name_a = type_a.split(".")[-1].replace("_", " ").title()
    name_b = type_b.split(".")[-1].replace("_", " ").title()
    return 0.0, "incompatible", f"Incompatible categories: {name_a} vs {name_b}"


def _compare_category(cat_a: Optional[str], cat_b: Optional[str]) -> Optional[float]:
    """Compare categories using principled category compatibility engine."""
    if not cat_a and not cat_b:
        return None
    type_a = resolve_canonical_object_type(cat_a)
    type_b = resolve_canonical_object_type(cat_b)
    score, _, _ = compute_category_compatibility(type_a, type_b, cat_a, cat_b)
    return score


def _compare_colors(
    p1: Optional[str], s1: Optional[str],
    p2: Optional[str], s2: Optional[str]
) -> Tuple[Optional[float], Optional[str]]:
    """
    Compare primary and secondary color combinations.
    Returns (score in [0.0, 1.0], match_type)
    """
    if not p1 and not p2:
        return None, None
    if not p1 or not p2:
        return None, None

    c1 = p1.lower().strip()
    c2 = p2.lower().strip()

    # Exact primary match
    if c1 == c2:
        if s1 and s2 and s1.lower().strip() == s2.lower().strip():
            return 1.0, "exact_both"
        return 0.90, "exact_primary"

    # Related color shade (e.g. silver and grey)
    if (c1, c2) in COLOR_SIMILARITY:
        return COLOR_SIMILARITY[(c1, c2)], "related_shade"

    # Secondary cross-match when primary colors differ
    # One item's primary matches the other's accent
    if (s2 and c1 == s2.lower().strip()) or (s1 and c2 == s1.lower().strip()):
        return 0.30, "accent_overlap"

    return 0.0, "mismatch"


def _compare_shapes(s1: Optional[str], s2: Optional[str]) -> Optional[float]:
    """Compare geometric shapes."""
    if not s1 or not s2:
        return None
    a = s1.lower().strip()
    b = s2.lower().strip()
    if a == b:
        return 1.0
    if (a, b) in SHAPE_SIMILARITY:
        return SHAPE_SIMILARITY[(a, b)]
    return 0.20


def _compare_sizes(s1: Optional[str], s2: Optional[str]) -> Optional[float]:
    """Compare size categories (Small, Medium, Large)."""
    if not s1 or not s2:
        return None
    a = s1.lower().strip()
    b = s2.lower().strip()
    if a == b:
        return 1.0
    # Adjacent sizes
    if (a == "small" and b == "medium") or (a == "medium" and b in ("small", "large")) or (a == "large" and b == "medium"):
        return 0.60
    # Opposite sizes
    if (a == "small" and b == "large") or (a == "large" and b == "small"):
        return 0.10
    return 0.40


def _compare_capacity(c1: Optional[float], c2: Optional[float]) -> Optional[float]:
    """Compare volume capacity in litres for applicable containers."""
    if c1 is None or c2 is None:
        return None
    if c1 <= 0 or c2 <= 0:
        return None

    rel_diff = abs(c1 - c2) / max(c1, c2)
    if rel_diff <= 0.15:
        return 1.0
    if rel_diff <= 0.35:
        return 0.70
    if rel_diff <= 0.50:
        return 0.40
    return 0.10


def _compare_materials(m1: Optional[str], m2: Optional[str]) -> Optional[float]:
    """Compare material and surface texture."""
    if not m1 or not m2:
        return None
    a = m1.lower().strip()
    b = m2.lower().strip()
    if a == b:
        return 1.0
    if ("leather" in a and "leather" in b) or ("fabric" in a and "fabric" in b) or ("plastic" in a and "plastic" in b) or ("metal" in a and "metal" in b):
        return 0.90
    return 0.15


def _find_shared_distinctive_features(
    list1: List[str], list2: List[str]
) -> List[Tuple[str, str, float]]:
    """Identify matching or fuzzy-overlapping distinctive features."""
    shared = []
    for f1 in list1:
        f1_norm = f1.lower().strip()
        for f2 in list2:
            f2_norm = f2.lower().strip()
            if f1_norm == f2_norm:
                shared.append((f1, f2, 1.0))
                break
            # Fuzzy match ratio (e.g. 'red keychain' vs 'red key chain')
            ratio = difflib.SequenceMatcher(None, f1_norm, f2_norm).ratio()
            if ratio >= 0.80:
                shared.append((f1, f2, round(ratio, 2)))
                break
            # Substring match (e.g. 'pikachu keychain' matches 'keychain')
            if f1_norm in f2_norm or f2_norm in f1_norm:
                shared.append((f1, f2, 0.85))
                break
    return shared


# ---------------------------------------------------------------------------
# CORE ATTRIBUTE COMPARISON & EXPLANATION
# ---------------------------------------------------------------------------

def compare_attributes(
    attrs1: ItemAttributes,
    attrs2: ItemAttributes,
    canonical_type1: Optional[str] = None,
    canonical_type2: Optional[str] = None,
) -> Tuple[float, Dict[str, Any], MatchExplanation]:
    """
    Compare two ItemAttributes representations.
    Adheres strictly to the principles:
    1. Unknown attributes never count as mismatches or penalize candidates.
    2. Common attributes (e.g. black color) carry modest weight; high-specificity features (e.g. red keychain) carry high weight.
    3. Produces concise, human-readable explanations.
    """
    dimension_scores: Dict[str, float] = {}
    breakdown: Dict[str, str] = {}
    reasons: List[str] = []

    # 1. Distinctive Features (Highest specificity)
    shared_features = _find_shared_distinctive_features(
        attrs1.distinctive_features, attrs2.distinctive_features
    )
    shared_names = [f[0] for f in shared_features]

    if shared_features:
        dimension_scores["distinctive_features"] = max(f[2] for f in shared_features)
        breakdown["distinctive_features"] = f"Shared: {', '.join(shared_names)}"
        for f in shared_names:
            reasons.append(f"Matching distinctive feature: {f}")
    elif attrs1.distinctive_features and attrs2.distinctive_features:
        # Both had distinctive features listed, but none matched
        dimension_scores["distinctive_features"] = 0.20
        breakdown["distinctive_features"] = "Different distinctive features reported"
    else:
        breakdown["distinctive_features"] = "Distinctive features unspecified in one or both reports"

    # 2. Category Compatibility
    type1 = canonical_type1 or resolve_canonical_object_type(attrs1.category)
    type2 = canonical_type2 or resolve_canonical_object_type(attrs2.category)
    cat_score, cat_tier, cat_reason = compute_category_compatibility(
        type1, type2, attrs1.category, attrs2.category
    )
    dimension_scores["category"] = cat_score
    breakdown["category"] = f"'{attrs1.category or 'unspecified'}' vs '{attrs2.category or 'unspecified'}'"
    if cat_tier in ("exact", "broad", "related"):
        reasons.append(cat_reason)
    else:
        breakdown["category"] += f" (category mismatch: {cat_reason})"

    # 3. Color
    color_score, color_type = _compare_colors(
        attrs1.primary_color, attrs1.secondary_color,
        attrs2.primary_color, attrs2.secondary_color,
    )
    if color_score is not None:
        dimension_scores["color"] = color_score
        c1_desc = f"{attrs1.primary_color}" + (f" with {attrs1.secondary_color}" if attrs1.secondary_color else "")
        c2_desc = f"{attrs2.primary_color}" + (f" with {attrs2.secondary_color}" if attrs2.secondary_color else "")
        breakdown["color"] = f"'{c1_desc}' vs '{c2_desc}'"
        if color_type == "exact_both":
            reasons.append(f"Matching primary and accent colors ({c1_desc})")
        elif color_type == "exact_primary":
            reasons.append(f"Matching color scheme ({attrs1.primary_color})")
        elif color_type == "related_shade":
            reasons.append(f"Similar color shade ({attrs1.primary_color} vs {attrs2.primary_color})")
        elif color_type == "accent_overlap":
            # Primary colors differ! Do NOT claim matching color scheme
            shared_accent = (
                attrs1.primary_color
                if (attrs2.secondary_color and attrs1.primary_color.lower() == attrs2.secondary_color.lower())
                else attrs2.primary_color
            )
            breakdown["color"] += f" (primary color mismatch; accent {shared_accent} overlap)"
        else:
            breakdown["color"] += " (color mismatch)"
    else:
        breakdown["color"] = "Color unspecified in one or both reports"

    # 4. Shape (only add supporting reason if category is at least related)
    shape_score = _compare_shapes(attrs1.shape, attrs2.shape)
    if shape_score is not None:
        dimension_scores["shape"] = shape_score
        breakdown["shape"] = f"'{attrs1.shape}' vs '{attrs2.shape}'"
        if shape_score >= 0.70 and cat_score >= 0.30:
            reasons.append(f"Matching shape ({attrs1.shape})")
    else:
        breakdown["shape"] = "Shape unspecified"

    # 5. Size (only add supporting reason if category is at least related)
    size_score = _compare_sizes(attrs1.size_category, attrs2.size_category)
    if size_score is not None:
        dimension_scores["size"] = size_score
        breakdown["size"] = f"'{attrs1.size_category}' vs '{attrs2.size_category}'"
        if size_score >= 0.60 and cat_score >= 0.30:
            reasons.append(f"Compatible size category ({attrs1.size_category})")
    else:
        breakdown["size"] = "Size category unspecified"

    # 6. Capacity (only if applicable and specified)
    cap_score = _compare_capacity(attrs1.capacity_litres, attrs2.capacity_litres)
    if cap_score is not None:
        dimension_scores["capacity"] = cap_score
        breakdown["capacity"] = f"{attrs1.capacity_text or attrs1.capacity_litres}L vs {attrs2.capacity_text or attrs2.capacity_litres}L"
        if cap_score >= 0.70:
            reasons.append(f"Matching capacity ({attrs1.capacity_text or f'{attrs1.capacity_litres}L'})")
    else:
        breakdown["capacity"] = "Capacity unknown in one or both reports (omitted from score)"

    # 7. Material
    mat_score = _compare_materials(attrs1.material, attrs2.material)
    if mat_score is not None:
        dimension_scores["material"] = mat_score
        breakdown["material"] = f"'{attrs1.material}' vs '{attrs2.material}'"
        if mat_score >= 0.80 and cat_score >= 0.30:
            reasons.append(f"Matching material/texture ({attrs1.material})")
    else:
        breakdown["material"] = "Material unspecified"

    # Weighted Attribute Aggregation
    # Inherent informativeness weights: distinctive features (0.35) > category (0.25) > color (0.15) > shape/size/capacity/material (0.10)
    INFORMATIVENESS_WEIGHTS = {
        "distinctive_features": 0.35,
        "category": 0.20,
        "color": 0.20,
        "shape": 0.10,
        "size": 0.10,
        "capacity": 0.15,
        "material": 0.10,
    }

    if dimension_scores:
        total_weight = sum(INFORMATIVENESS_WEIGHTS[dim] for dim in dimension_scores)
        weighted_sum = sum(INFORMATIVENESS_WEIGHTS[dim] * score for dim, score in dimension_scores.items())
        final_attribute_score = round((weighted_sum / total_weight) * 100, 2)
    else:
        final_attribute_score = 0.0

    # Summary synthesis
    if shared_features:
        summary = f"Strong match: agreed on key attributes and shared distinctive feature ({', '.join(shared_names)})."
    elif len(reasons) >= 3:
        summary = f"Plausible match: multiple agreeing physical attributes ({', '.join(r.split('(')[-1].rstrip(')') for r in reasons[:3])})."
    elif len(reasons) >= 1:
        summary = f"Partial match: {reasons[0].lower()}."
    else:
        summary = "Low attribute overlap or insufficient confirmed details."

    calibration_note = (
        "Uncertain or omitted attributes (such as capacity or internal contents) were omitted from "
        "scoring without penalizing the candidate. Always inspect the physical item or verify unique serials."
    )

    explanation = MatchExplanation(
        summary=summary,
        reasons=reasons,
        shared_distinctive_features=shared_names,
        attribute_breakdown=breakdown,
        confidence_calibration_note=calibration_note,
    )

    metadata_dict = {
        "dimension_scores": dimension_scores,
        "compared_dimensions_count": len(dimension_scores),
        "shared_features_count": len(shared_features),
        "category_compatibility": cat_score,
        "category_tier": cat_tier,
    }

    return final_attribute_score, metadata_dict, explanation


def calculate_composite_match_score(
    visual_score: Optional[float] = None,
    text_score: Optional[float] = None,
    attribute_score: Optional[float] = None,
    location_score: Optional[float] = None,
    time_score: Optional[float] = None,
    has_distinctive_match: bool = False,
    category_compatibility: float = 1.0,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Combine visual similarity, semantic text similarity, physical attribute score,
    location proximity, and time proximity into a single bounded composite score [0.0, 100.0],
    gated by category compatibility.
    """
    default_weights = {
        "visual": 0.35,
        "text": 0.25,
        "attributes": 0.25,
        "location": 0.10,
        "time": 0.05,
    }
    w = dict(weights or default_weights)

    available_components: Dict[str, float] = {}
    if visual_score is not None:
        available_components["visual"] = visual_score
    if text_score is not None:
        available_components["text"] = text_score
    if attribute_score is not None:
        available_components["attributes"] = attribute_score
    if location_score is not None:
        available_components["location"] = location_score
    if time_score is not None:
        available_components["time"] = time_score

    if not available_components:
        return 0.0

    total_weight = sum(w[key] for key in available_components)
    base_score = sum(w[key] * val for key, val in available_components.items()) / total_weight

    # Boost score if a distinctive feature is proven identical (only if category is compatible)
    if has_distinctive_match and category_compatibility >= 0.30:
        base_score = min(100.0, base_score + 8.0)

    # Category compatibility gating:
    # A fundamental category mismatch cannot be offset by matching color or visual background.
    if category_compatibility <= 0.05:
        # Incompatible object type: capped to negligible value
        final_score = base_score * 0.05
    elif category_compatibility < 0.80:
        # Related object type (e.g. Earbuds vs Neckband): scaled down proportionally
        scaling = 0.20 + 0.80 * category_compatibility
        final_score = base_score * scaling
    else:
        final_score = base_score

    return round(max(0.0, min(100.0, final_score)), 2)
