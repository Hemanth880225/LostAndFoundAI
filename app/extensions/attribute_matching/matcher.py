"""Attribute-aware comparison engine, distinctive feature weighting, and explainability generator."""

import difflib
from typing import Any, Dict, List, Optional, Tuple

from app.extensions.attribute_matching.schemas import ItemAttributes, MatchExplanation


# Related subcategories that share significant functional and visual overlap
CATEGORY_SYNONYMS = {
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


def _compare_category(cat_a: Optional[str], cat_b: Optional[str]) -> Optional[float]:
    """Compare categories, accommodating generic vs specific naming (e.g. bag vs backpack)."""
    if not cat_a or not cat_b:
        return None
    a = cat_a.lower().strip()
    b = cat_b.lower().strip()
    if a == b:
        return 1.0
    if b in CATEGORY_SYNONYMS.get(a, set()) or a in CATEGORY_SYNONYMS.get(b, set()):
        return 0.80
    return 0.0


def _compare_colors(
    p1: Optional[str], s1: Optional[str],
    p2: Optional[str], s2: Optional[str]
) -> Optional[float]:
    """Compare primary and secondary color combinations."""
    if not p1 and not p2:
        return None
    if not p1 or not p2:
        return None

    c1 = p1.lower().strip()
    c2 = p2.lower().strip()

    # Exact primary match
    if c1 == c2:
        # Check secondary color bonus
        if s1 and s2 and s1.lower().strip() == s2.lower().strip():
            return 1.0
        return 0.90

    # Cross match: primary matches secondary
    if (s2 and c1 == s2.lower().strip()) or (s1 and c2 == s1.lower().strip()):
        return 0.75

    # Related color shade
    if (c1, c2) in COLOR_SIMILARITY:
        return COLOR_SIMILARITY[(c1, c2)]

    return 0.0


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

    # 2. Category
    cat_score = _compare_category(attrs1.category, attrs2.category)
    if cat_score is not None:
        dimension_scores["category"] = cat_score
        breakdown["category"] = f"'{attrs1.category}' vs '{attrs2.category}'"
        if cat_score >= 0.80:
            reasons.append(f"Compatible category ({attrs1.category or attrs2.category})")
        else:
            breakdown["category"] += " (category mismatch)"
    else:
        breakdown["category"] = "Category unspecified"

    # 3. Color
    color_score = _compare_colors(
        attrs1.primary_color, attrs1.secondary_color,
        attrs2.primary_color, attrs2.secondary_color,
    )
    if color_score is not None:
        dimension_scores["color"] = color_score
        c1_desc = f"{attrs1.primary_color}" + (f" with {attrs1.secondary_color}" if attrs1.secondary_color else "")
        c2_desc = f"{attrs2.primary_color}" + (f" with {attrs2.secondary_color}" if attrs2.secondary_color else "")
        breakdown["color"] = f"'{c1_desc}' vs '{c2_desc}'"
        if color_score >= 0.75:
            reasons.append(f"Matching color scheme ({c1_desc})")
        else:
            breakdown["color"] += " (color mismatch)"
    else:
        breakdown["color"] = "Color unspecified in one or both reports"

    # 4. Shape
    shape_score = _compare_shapes(attrs1.shape, attrs2.shape)
    if shape_score is not None:
        dimension_scores["shape"] = shape_score
        breakdown["shape"] = f"'{attrs1.shape}' vs '{attrs2.shape}'"
        if shape_score >= 0.70:
            reasons.append(f"Matching shape ({attrs1.shape})")
    else:
        breakdown["shape"] = "Shape unspecified"

    # 5. Size
    size_score = _compare_sizes(attrs1.size_category, attrs2.size_category)
    if size_score is not None:
        dimension_scores["size"] = size_score
        breakdown["size"] = f"'{attrs1.size_category}' vs '{attrs2.size_category}'"
        if size_score >= 0.60:
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
        if mat_score >= 0.80:
            reasons.append(f"Matching material/texture ({attrs1.material})")
    else:
        breakdown["material"] = "Material unspecified"

    # Weighted Attribute Aggregation
    # Inherent informativeness weights: distinctive features (0.35) > category (0.20) > color (0.15) > shape/size/capacity/material (0.10)
    INFORMATIVENESS_WEIGHTS = {
        "distinctive_features": 0.35,
        "category": 0.20,
        "color": 0.15,
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
    }

    return final_attribute_score, metadata_dict, explanation


def calculate_composite_match_score(
    visual_score: Optional[float] = None,
    text_score: Optional[float] = None,
    attribute_score: Optional[float] = None,
    location_score: Optional[float] = None,
    time_score: Optional[float] = None,
    has_distinctive_match: bool = False,
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Combine visual similarity, semantic text similarity, physical attribute score,
    location proximity, and time proximity into a single bounded composite score [0.0, 100.0].
    """
    default_weights = {
        "visual": 0.35,
        "text": 0.25,
        "attributes": 0.20,
        "location": 0.12,
        "time": 0.08,
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
    score = sum(w[key] * val for key, val in available_components.items()) / total_weight

    # Boost score if a rare/distinctive feature is proven identical (e.g. red keychain or unique sticker)
    if has_distinctive_match:
        score = min(100.0, score + 8.0)

    return round(score, 2)
