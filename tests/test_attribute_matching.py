"""Comprehensive unit, API, integration, and benchmark evaluation suite for Attribute-Based AI Matching."""

import io
import json
from datetime import date
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base, get_db
from app.db.models import ItemImage, ItemReport
from app.extensions.attribute_matching.evaluation import (
    evaluate_attribute_search_quality,
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.extensions.attribute_matching.extractor import (
    extract_attributes_from_image,
    extract_attributes_from_text,
    merge_attributes,
)
from app.extensions.attribute_matching.matcher import (
    calculate_composite_match_score,
    compare_attributes,
    compute_category_compatibility,
    resolve_canonical_object_type,
)
from app.extensions.attribute_matching.models import ItemAttributeRecord
from app.extensions.attribute_matching.schemas import (
    AttributeFilterRequest,
    ItemAttributes,
)
from app.extensions.attribute_matching.service import (
    calibrate_clip_visual_similarity,
    get_or_create_attributes,
    search_by_attributes,
)
from app.main import app


def make_test_png(color="blue", size=(32, 32)) -> bytes:
    """Generate valid PNG bytes with specified color."""
    buf = io.BytesIO()
    img = Image.new("RGB", size, color=color)
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def test_db():
    """Isolated in-memory SQLite database for attribute testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = TestingSession()

    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def api_client(test_db):
    """FastAPI TestClient with overridden in-memory database."""
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 1. VISUAL & PHYSICAL ATTRIBUTE RECOGNITION (TEXT & VISION)
# ---------------------------------------------------------------------------

def test_text_attribute_extraction_comprehensive():
    """Verify recognition of color combinations, shapes, sizes, capacities, and distinctive features."""
    title = "Wildcraft Trailblazer Backpack"
    desc = (
        "Medium-sized rectangular black backpack with grey accents. "
        "Estimated capacity 20-30 litres. Made of durable fabric/canvas. "
        "Has a distinctive red keychain and front zipper pocket."
    )

    attrs = extract_attributes_from_text(title=title, description=desc)

    assert attrs.category == "Backpack"
    assert attrs.primary_color == "Black"
    assert attrs.secondary_color == "Grey"
    assert attrs.shape == "Rectangular"
    assert attrs.size_category == "Medium"
    assert attrs.capacity_litres == 25.0  # Midpoint of 20-30 litres
    assert "20–30 litres" in attrs.capacity_text
    assert attrs.material == "Fabric/Canvas"
    assert any("Red keychain" in f for f in attrs.distinctive_features)
    assert any("Front zipper pocket" in f for f in attrs.distinctive_features)


def test_capacity_not_forced_on_inapplicable_objects():
    """Verify capacity is not fabricated or forced onto keys, wallets, or coins."""
    key_desc = "Found a silver metallic house key with a blue plastic tag."
    key_attrs = extract_attributes_from_text(title="House Key", description=key_desc, category="Keys")

    assert key_attrs.capacity_litres is None
    assert key_attrs.capacity_text is None
    assert key_attrs.material == "Metal"
    assert key_attrs.primary_color == "Blue" or key_attrs.primary_color == "Silver"


def test_image_attribute_extraction_pil_colors():
    """Verify visual extraction of dominant colors from valid image bytes."""
    # Create an image that is 80% red and 20% white
    img = Image.new("RGB", (64, 64), color="red")
    # Draw a white patch
    for x in range(25):
        for y in range(25):
            img.putpixel((x, y), (255, 255, 255))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    attrs = extract_attributes_from_image(png_bytes)
    assert attrs.primary_color == "Red"
    assert attrs.secondary_color in ("White", None)


def test_merge_attributes_priority():
    """Verify explicit user text takes priority and vision fills gaps."""
    text_attrs = ItemAttributes(
        category="Backpack",
        primary_color="Black",
        shape=None,  # missing in text
    )
    image_attrs = ItemAttributes(
        category="Handbag",  # vision guessed handbag
        primary_color="Blue",  # vision guessed blue due to background
        shape="Rectangular",  # vision successfully detected shape
        material="Fabric/Canvas",
    )

    merged = merge_attributes(text_attrs, image_attrs)
    assert merged.category == "Backpack"  # Text won
    assert merged.primary_color == "Black"  # Text won
    assert merged.shape == "Rectangular"  # Vision filled gap
    assert merged.material == "Fabric/Canvas"  # Vision filled gap


# ---------------------------------------------------------------------------
# 2. INCOMPLETE INFORMATION & ATTRIBUTE COMPARISON
# ---------------------------------------------------------------------------

def test_missing_attribute_does_not_penalize():
    """
    Verify the mandatory requirement:
    Unknown capacity or missing details must neither count as a mismatch
    nor artificially reduce match confidence.
    """
    lost = ItemAttributes(
        category="Backpack",
        primary_color="Black",
        secondary_color="Grey",
        shape="Rectangular",
        size_category="Medium",
        capacity_litres=25.0,
        distinctive_features=["Red keychain"],
    )

    # Found report where finder provided only category, color, shape, and distinctive feature
    found = ItemAttributes(
        category="Backpack",
        primary_color="Black",
        secondary_color=None,  # unknown
        shape="Rectangular",
        size_category=None,  # unknown
        capacity_litres=None,  # unknown
        distinctive_features=["Red keychain"],
    )

    score, meta, explanation = compare_attributes(lost, found)

    assert score >= 85.0  # Strong agreement on all known attributes
    assert "Red keychain" in explanation.shared_distinctive_features
    assert "Capacity unknown in one or both reports (omitted from score)" in explanation.attribute_breakdown["capacity"]
    assert any("Matching distinctive feature: Red keychain" in r for r in explanation.reasons)


def test_conflicting_attributes_reduce_score():
    """Verify distinct colors or conflicting shapes result in low attribute scores."""
    lost_wallet = ItemAttributes(
        category="Wallet",
        primary_color="Black",
        material="Leather-like",
    )
    found_red_plastic_wallet = ItemAttributes(
        category="Wallet",
        primary_color="Red",
        material="Plastic",
    )

    score, _, explanation = compare_attributes(lost_wallet, found_red_plastic_wallet)
    assert score < 50.0
    assert "color mismatch" in explanation.attribute_breakdown["color"].lower()


def test_distinctive_features_outweigh_common_color():
    """
    Verify the mandatory requirement:
    Matching color alone contributes less than distinctive features.
    """
    # Case A: Two generic black backpacks with no distinctive features
    lost_generic = ItemAttributes(category="Backpack", primary_color="Black")
    found_generic = ItemAttributes(category="Backpack", primary_color="Black")
    score_generic, _, exp_generic = compare_attributes(lost_generic, found_generic)

    # Case B: Two backpacks with a rare shared distinctive feature ("Pikachu charm")
    lost_distinctive = ItemAttributes(
        category="Backpack", primary_color="Black", distinctive_features=["Pikachu charm"]
    )
    found_distinctive = ItemAttributes(
        category="Backpack", primary_color="Black", distinctive_features=["Pikachu charm"]
    )
    score_distinctive, _, exp_distinctive = compare_attributes(lost_distinctive, found_distinctive)

    assert score_distinctive > score_generic
    assert len(exp_distinctive.shared_distinctive_features) == 1
    assert "Pikachu charm" in exp_distinctive.shared_distinctive_features[0]


# ---------------------------------------------------------------------------
# 3. DATABASE CACHING & SERVICE LAYER
# ---------------------------------------------------------------------------

def test_get_or_create_attributes_caches_in_database(test_db):
    """Verify attributes are extracted on first call and cached in item_attributes table."""
    report = ItemReport(
        report_type="lost",
        item_name="Dell XPS 15",
        category="Electronics",
        color="Silver",
        description="Silver rectangular laptop with matte finish and Apple sticker on lid.",
        event_date=date.today(),
        location_text="Library 2nd Floor",
        status="active",
    )
    test_db.add(report)
    test_db.commit()
    test_db.refresh(report)

    # First call: extracts and inserts into database
    attrs1 = get_or_create_attributes(test_db, report)
    assert attrs1.primary_color == "Silver"
    assert attrs1.shape == "Rectangular"
    assert any("Apple sticker" in f for f in attrs1.distinctive_features)

    # Verify database record exists
    record = test_db.query(ItemAttributeRecord).filter_by(report_id=report.id).first()
    assert record is not None
    assert record.primary_color == "Silver"

    # Second call: retrieves directly from database without re-extraction
    attrs2 = get_or_create_attributes(test_db, report)
    assert attrs2.primary_color == attrs1.primary_color
    assert attrs2.distinctive_features == attrs1.distinctive_features


# ---------------------------------------------------------------------------
# 4. ATTRIBUTE SEARCH & FILTER API ENDPOINTS
# ---------------------------------------------------------------------------

def test_api_attribute_taxonomy(api_client):
    """Verify taxonomy endpoint provides categories, shapes, colors, and materials."""
    resp = api_client.get("/api/attributes/taxonomy")
    assert resp.status_code == 200
    data = resp.json()
    assert "Backpack" in data["categories"]
    assert "Rectangular" in data["shapes"]
    assert "Black" in data["primary_colors"]
    assert "Leather-like" in data["materials"]


def test_api_extract_attributes_json(api_client):
    """Verify /api/attributes/extract endpoint extracts attributes from JSON."""
    resp = api_client.post(
        "/api/attributes/extract",
        json={
            "title": "Nike Sports Duffel Bag",
            "description": "Large cylindrical blue duffel bag with white accents and Adidas keychain.",
            "category": "Duffel Bag",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    attrs = data["attributes"]
    assert attrs["category"] == "Duffel Bag"
    assert attrs["primary_color"] == "Blue"
    assert attrs["secondary_color"] == "White"
    assert attrs["shape"] == "Cylindrical"
    assert attrs["size_category"] == "Large"
    assert any("Adidas keychain" in f for f in attrs["distinctive_features"])


def test_api_attribute_search_soft_versus_hard_filters(api_client, test_db):
    """
    Verify difference between soft preferences and hard filters:
    - Soft filters boost candidates with matching attributes but don't exclude items with unknown attributes.
    - Hard filters strictly exclude non-matching items.
    """
    # Seed reports
    rep_black_bag = ItemReport(
        report_type="found",
        item_name="Black Backpack",
        category="Backpack",
        color="Black",
        description="Black rectangular backpack found in canteen.",
        event_date=date.today(),
        location_text="Canteen",
        status="active",
    )
    rep_blue_bottle = ItemReport(
        report_type="found",
        item_name="Blue Bottle",
        category="Water Bottle",
        color="Blue",
        description="Cylindrical blue bottle.",
        event_date=date.today(),
        location_text="Gym",
        status="active",
    )
    test_db.add_all([rep_black_bag, rep_blue_bottle])
    test_db.commit()

    # 1. Soft filter: Search for Backpack
    soft_resp = api_client.post(
        "/api/attributes/search",
        json={"category": "Backpack", "hard_filters": [], "min_score": 0.0},
    )
    assert soft_resp.status_code == 200
    soft_data = soft_resp.json()
    # Both are returned, but Backpack ranks first with higher score
    assert soft_data["candidate_count"] == 2
    assert soft_data["matches"][0]["report_id"] == rep_black_bag.id
    assert soft_data["matches"][0]["match_score"] > soft_data["matches"][1]["match_score"]

    # 2. Hard filter: Strictly Category = Backpack
    hard_resp = api_client.post(
        "/api/attributes/search",
        json={"category": "Backpack", "hard_filters": ["category"]},
    )
    assert hard_resp.status_code == 200
    hard_data = hard_resp.json()
    assert hard_data["candidate_count"] == 1
    assert hard_data["matches"][0]["report_id"] == rep_black_bag.id


def test_api_image_only_search_with_attribute_extraction(api_client, test_db):
    """Verify uploading a query image returns candidates with detected query attributes and explanations."""
    rep = ItemReport(
        report_type="found",
        item_name="Blue Umbrella",
        category="Umbrella",
        color="Blue",
        description="Blue umbrella with curved wooden handle.",
        event_date=date.today(),
        location_text="Campus Gate",
        status="active",
    )
    test_db.add(rep)
    test_db.commit()
    test_db.refresh(rep)

    # Attach an image to the report
    img_record = ItemImage(
        report_id=rep.id,
        image_path="uploads/test_umbrella.png",
        content_type="image/png",
    )
    test_db.add(img_record)
    test_db.commit()

    # Search with a query photo
    query_png = make_test_png(color="blue")
    files = [("files", ("query_umbrella.png", query_png, "image/png"))]

    resp = api_client.post("/api/attributes/search", files=files)
    assert resp.status_code == 200
    data = resp.json()

    assert data["query_image_count"] == 1
    assert data["query_attributes"]["primary_color"] == "Blue"
    assert len(data["matches"]) >= 1
    top_match = data["matches"][0]
    assert top_match["report_id"] == rep.id
    assert "explanation" in top_match
    assert len(top_match["explanation"]["reasons"]) > 0


# ---------------------------------------------------------------------------
# 5. RANKING QUALITY EVALUATION (P@K, R@K, MRR BENCHMARK)
# ---------------------------------------------------------------------------

def test_evaluation_metric_calculators():
    """Verify precision, recall, and reciprocal rank calculations."""
    ground_truth = {101, 102}

    # Perfect ranking: [101, 102, 103, 104]
    ranking_perfect = [101, 102, 103, 104]
    assert precision_at_k(ground_truth, ranking_perfect, k=1) == 1.0
    assert precision_at_k(ground_truth, ranking_perfect, k=2) == 1.0
    assert precision_at_k(ground_truth, ranking_perfect, k=4) == 0.5
    assert recall_at_k(ground_truth, ranking_perfect, k=2) == 1.0
    assert reciprocal_rank(ground_truth, ranking_perfect) == 1.0

    # Sub-optimal ranking: [103, 101, 104]
    ranking_sub = [103, 101, 104]
    assert precision_at_k(ground_truth, ranking_sub, k=1) == 0.0
    assert precision_at_k(ground_truth, ranking_sub, k=2) == 0.5
    assert reciprocal_rank(ground_truth, ranking_sub) == 0.5

    # Mean Reciprocal Rank
    queries_gt = {"q1": {101}, "q2": {201}}
    rankings = {"q1": [101, 102], "q2": [999, 201]}
    # q1 RR = 1.0, q2 RR = 0.5 -> MRR = 0.75
    assert mean_reciprocal_rank(queries_gt, rankings) == 0.75


def test_ranking_benchmark_with_labelled_pairs(test_db):
    """
    Evaluate ranking quality on a labelled ground-truth benchmark:
    - Target 1: Black rectangular backpack with red keychain
    - Target 2: Stainless steel cylindrical water bottle
    - Distractors: Multiple other items (wallets, phones, watches)
    Verifies Mean Reciprocal Rank and Precision metrics.
    """
    # 1. Target Pair 1 (Found item)
    found_backpack = ItemReport(
        report_type="found",
        item_name="Black Backpack",
        category="Backpack",
        color="Black",
        description="Black rectangular backpack with red keychain found in library.",
        event_date=date.today(),
        location_text="Library",
        status="active",
    )

    # 2. Target Pair 2 (Found item)
    found_bottle = ItemReport(
        report_type="found",
        item_name="Stainless Steel Bottle",
        category="Water Bottle",
        color="Silver",
        description="750ml cylindrical silver water bottle left in sports room.",
        event_date=date.today(),
        location_text="Sports Room",
        status="active",
    )

    # 3. Distractor Items
    distractor_wallet = ItemReport(
        report_type="found",
        item_name="Brown Leather Wallet",
        category="Wallet",
        color="Brown",
        description="Brown leather bifold wallet.",
        event_date=date.today(),
        location_text="Auditorium",
        status="active",
    )
    distractor_bag = ItemReport(
        report_type="found",
        item_name="Blue Travel Bag",
        category="Duffel Bag",
        color="Blue",
        description="Blue round duffel bag without tags.",
        event_date=date.today(),
        location_text="Station",
        status="active",
    )

    test_db.add_all([found_backpack, found_bottle, distractor_wallet, distractor_bag])
    test_db.commit()
    test_db.refresh(found_backpack)
    test_db.refresh(found_bottle)

    # Define Labelled Test Queries
    labelled_suite = [
        {
            "query_id": "query_lost_backpack_with_keychain",
            "request": AttributeFilterRequest(
                query_text="Lost my medium black rectangular backpack with a red keychain near library",
                category="Backpack",
                primary_color="Black",
                shape="Rectangular",
                distinctive_features="Red keychain",
            ),
            "target_report_ids": {found_backpack.id},
        },
        {
            "query_id": "query_lost_silver_bottle",
            "request": AttributeFilterRequest(
                query_text="Lost my 750ml silver cylindrical water bottle in sports complex",
                category="Water Bottle",
                primary_color="Silver",
                shape="Cylindrical",
            ),
            "target_report_ids": {found_bottle.id},
        },
    ]

    metrics = evaluate_attribute_search_quality(db=test_db, labelled_queries=labelled_suite)

    assert metrics["total_queries_evaluated"] == 2
    assert metrics["mrr"] >= 0.85  # Target found at rank 1 in both queries
    assert metrics["precision_at_1"] == 1.0  # Top rank is always the ground truth
    assert metrics["recall_at_3"] == 1.0  # All ground truth targets retrieved in top 3


# ---------------------------------------------------------------------------
# 6. REGRESSION TESTS: METADATA CONFIDENCE & MULTIPART/FORM SEARCH
# ---------------------------------------------------------------------------

def test_regression_confidence_scores_with_string_metadata(test_db):
    """
    Regression test: Ensure ItemAttributes and get_or_create_attributes can safely
    handle records whose confidence_scores dictionary contains string metadata or
    provenance tags (e.g. 'source': 'pdf_and_expert_curation') without ValidationError.
    """
    report = ItemReport(
        report_type="found",
        item_name="Imported WROGN Backpack",
        category="Backpack",
        color="Dark Blue/Black",
        description="Blue and black backpack found in room 302.",
        event_date=date.today(),
        location_text="Room 302",
        status="active",
    )
    test_db.add(report)
    test_db.commit()
    test_db.refresh(report)

    # Manually persist attribute record with string metadata in confidence_scores
    record = ItemAttributeRecord(
        report_id=report.id,
        category="Backpack",
        primary_color="Black",
        secondary_color="Blue",
        shape="Rectangular",
        size_category="Medium",
        material="Fabric/Canvas",
        confidence_scores={"overall": 0.95, "source": "pdf_and_expert_curation"},
        raw_attributes={},
    )
    test_db.add(record)
    test_db.commit()

    # get_or_create_attributes must load successfully without float parsing error
    attrs = get_or_create_attributes(test_db, report)
    assert attrs.category == "Backpack"
    assert attrs.confidence_scores["source"] == "pdf_and_expert_curation"
    assert attrs.confidence_scores["overall"] == 0.95


def test_api_attribute_search_multipart_form_regression(api_client, test_db):
    """
    Regression test: Reproduce the exact form submission from the Photo Search page
    (/search/image) sending form data with text, category, color, shape,
    size, material, and distinctive features against reports with metadata in confidence_scores.
    Must return 200 OK (not 500 Internal Server Error).
    """
    # Create report with string metadata in confidence_scores
    rep = ItemReport(
        report_type="found",
        item_name="Found Black Wildcraft Backpack",
        category="Backpack",
        color="Black",
        description="Black rectangular backpack with red stripes.",
        event_date=date.today(),
        location_text="Library",
        status="active",
    )
    test_db.add(rep)
    test_db.commit()
    test_db.refresh(rep)

    record = ItemAttributeRecord(
        report_id=rep.id,
        category="Backpack",
        primary_color="Black",
        shape="Rectangular",
        size_category="Medium",
        material="Fabric",
        distinctive_features=["red stripes"],
        confidence_scores={"overall": 0.95, "source": "pdf_and_expert_curation"},
        raw_attributes={},
    )
    test_db.add(record)
    test_db.commit()

    # Send form data matching browser submission
    form_data = {
        "target_type": "found",
        "query_text": "backpack",
        "category": "Backpack",
        "primary_color": "Black",
        "shape": "Rectangular",
        "size_category": "Medium",
        "material": "Fabric",
        "distinctive_features": "stripes",
    }

    resp = api_client.post("/api/attributes/search", data=form_data)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["candidate_count"] >= 1
    assert data["matches"][0]["report_id"] == rep.id
    assert data["matches"][0]["match_score"] > 50.0
    assert "explanation" in data["matches"][0]


def test_api_attribute_search_empty_results_no_500(api_client, test_db):
    """Verify searching an empty database or non-matching strict filter returns 200 with empty list."""
    form_data = {
        "target_type": "found",
        "category": "NonExistentCategoryXYZ",
        "hard_filters": json.dumps(["category"]),
    }
    resp = api_client.post("/api/attributes/search", data=form_data)
    assert resp.status_code == 200
    data = resp.json()
    assert data["candidate_count"] == 0
    assert data["matches"] == []


# ---------------------------------------------------------------------------
# 5. OVERMATCHING PREVENTION & CATEGORY GATING BENCHMARK (TESTS A - J)
# ---------------------------------------------------------------------------

def test_scenario_a_earbuds_vs_earbuds_high_confidence():
    """Test A: Identical/compatible earbuds pair achieves strong score (>75) and matching category."""
    query_earbuds = ItemAttributes(
        category="Earbuds",
        primary_color="White",
        shape="Oval",
        size_category="Small",
    )
    cand_earbuds = ItemAttributes(
        category="Earphones",
        primary_color="White",
        shape="Oval",
        size_category="Small",
    )
    score, meta, explanation = compare_attributes(
        query_earbuds, cand_earbuds,
        canonical_type1="audio.earbuds",
        canonical_type2="audio.earbuds",
    )
    assert meta["category_compatibility"] == 1.0
    assert "Matching category (Earbuds)" in explanation.reasons

    composite = calculate_composite_match_score(
        visual_score=92.0,
        text_score=85.0,
        attribute_score=score,
        category_compatibility=meta["category_compatibility"],
    )
    assert composite >= 75.0, f"Expected >75 for matching earbuds, got {composite}"


def test_scenario_b_earbuds_vs_neckband_separated_score():
    """Test B: Related audio devices (earbuds vs neckband) receive ~10-40 score and related tier."""
    query_earbuds = ItemAttributes(
        category="Earbuds",
        primary_color="White",
        shape="Oval",
        size_category="Small",
    )
    cand_neckband = ItemAttributes(
        category="Earphones",
        primary_color="Black",
        secondary_color="White",
        shape="Curved",
        size_category="Small",
    )
    score, meta, explanation = compare_attributes(
        query_earbuds, cand_neckband,
        canonical_type1="audio.earbuds",
        canonical_type2="audio.neckband",
    )
    assert meta["category_compatibility"] == 0.40
    assert meta["category_tier"] == "related"
    assert any("Related audio category" in r for r in explanation.reasons)
    # Ensure neckband does NOT falsely claim matching color scheme
    assert not any("Matching color scheme" in r for r in explanation.reasons)

    composite = calculate_composite_match_score(
        visual_score=35.0,
        attribute_score=score,
        category_compatibility=meta["category_compatibility"],
    )
    assert 10.0 <= composite <= 40.0, f"Expected neckband score in [10, 40], got {composite}"


def test_scenario_c_earbuds_vs_charger_incompatible():
    """Test C: Incompatible categories (earbuds vs charger) score <= 10 in soft mode and are gated."""
    query_earbuds = ItemAttributes(
        category="Earbuds",
        primary_color="White",
        shape="Oval",
        size_category="Small",
    )
    cand_charger = ItemAttributes(
        category="Charger",
        primary_color="White",
        shape="Rectangular",
        size_category="Small",
    )
    score, meta, explanation = compare_attributes(
        query_earbuds, cand_charger,
        canonical_type1="audio.earbuds",
        canonical_type2="power.charger",
    )
    assert meta["category_compatibility"] == 0.0
    assert meta["category_tier"] == "incompatible"

    composite = calculate_composite_match_score(
        visual_score=45.0,
        attribute_score=score,
        category_compatibility=meta["category_compatibility"],
    )
    assert composite <= 10.0, f"Expected charger composite score <= 10, got {composite}"


def test_scenario_d_compatible_backpacks():
    """Test D: Compatible backpacks with matching traits achieve high score (>65)."""
    lost_backpack = ItemAttributes(
        category="Backpack",
        primary_color="Grey",
        secondary_color="Orange",
        shape="Curved / Rectangular",
        size_category="Medium",
    )
    found_backpack = ItemAttributes(
        category="Backpack",
        primary_color="Grey",
        secondary_color="Orange",
        shape="Curved / Rectangular",
        size_category="Medium",
    )
    score, meta, explanation = compare_attributes(
        lost_backpack, found_backpack,
        canonical_type1="bags.backpack",
        canonical_type2="bags.backpack",
    )
    assert meta["category_compatibility"] == 1.0
    assert score >= 80.0
    composite = calculate_composite_match_score(
        visual_score=85.0,
        attribute_score=score,
        category_compatibility=meta["category_compatibility"],
    )
    assert composite >= 65.0


def test_scenario_e_similar_color_different_object_rejected():
    """Test E: Same color across incompatible objects does not overmatch."""
    type1 = resolve_canonical_object_type("Glasses", "Black Spectacles", "")
    type2 = resolve_canonical_object_type("Laptop", "Black Lenovo ThinkPad", "")
    compat, tier, _ = compute_category_compatibility(type1, type2)
    assert compat == 0.0
    assert tier == "incompatible"

    composite = calculate_composite_match_score(
        visual_score=35.0,
        attribute_score=60.0,
        category_compatibility=compat,
    )
    assert composite <= 5.0


def test_scenario_f_unknown_attributes_not_penalized():
    """Test F: Unknown attributes (e.g. capacity or material unspecified) never reduce candidate score."""
    full_attrs = ItemAttributes(
        category="Water Bottle",
        primary_color="Silver",
        shape="Cylindrical",
        size_category="Medium",
        capacity_litres=1.0,
        material="Stainless Steel",
    )
    sparse_attrs = ItemAttributes(
        category="Water Bottle",
        primary_color="Silver",
    )
    score, meta, _ = compare_attributes(full_attrs, sparse_attrs)
    assert score >= 90.0, f"Expected >= 90.0 since all specified attributes matched, got {score}"


def test_scenario_g_distinctive_features_meaningful_boost():
    """Test G: Distinctive feature match boosts score noticeably above non-distinctive match."""
    plain1 = ItemAttributes(category="Backpack", primary_color="Black")
    plain2 = ItemAttributes(category="Backpack", primary_color="Black")
    score_plain, _, _ = compare_attributes(plain1, plain2)

    feat1 = ItemAttributes(category="Backpack", primary_color="Black", distinctive_features=["Red Ferrari Keychain"])
    feat2 = ItemAttributes(category="Backpack", primary_color="Black", distinctive_features=["Red Ferrari Keychain"])
    score_feat, meta_feat, explanation = compare_attributes(feat1, feat2)

    assert "Matching distinctive feature: Red Ferrari Keychain" in explanation.reasons
    comp_plain = calculate_composite_match_score(attribute_score=score_plain, has_distinctive_match=False)
    comp_feat = calculate_composite_match_score(attribute_score=score_feat, has_distinctive_match=True)
    assert comp_feat > comp_plain


def test_scenario_h_empty_search_results_handled_cleanly(test_db):
    """Test H: Attribute search that matches 0 candidates returns 200 with empty list."""
    req = AttributeFilterRequest(
        category="UnicornCarpetMagicItemXYZ",
        hard_filters=["category"],
    )
    res = search_by_attributes(test_db, req)
    assert res.candidate_count == 0
    assert len(res.matches) == 0


def test_scenario_i_strict_versus_soft_category_filter(test_db):
    """Test I: Strict category filter excludes incompatible and related candidates, soft mode ranks them lower."""
    rep_earbuds = ItemReport(
        report_type="found",
        item_name="White Earbuds with Case",
        category="Earphones",
        color="White",
        description="Found white wireless earbuds in charging case",
        location_text="Library",
        event_date=date.today(),
        status="active",
    )
    rep_charger = ItemReport(
        report_type="found",
        item_name="White Fast Charger",
        category="Charger",
        color="White",
        description="Found white 80W wall charger with usb cable",
        location_text="Cafeteria",
        event_date=date.today(),
        status="active",
    )
    rep_neckband = ItemReport(
        report_type="found",
        item_name="Black Wireless Neckband",
        category="Earphones",
        color="Black",
        description="Found black bluetooth neckband earphones",
        location_text="Sports Complex",
        event_date=date.today(),
        status="active",
    )
    test_db.add_all([rep_earbuds, rep_charger, rep_neckband])
    test_db.commit()

    # Soft search for Earbuds: only qualifying items (score >= 30%) are returned
    req_soft = AttributeFilterRequest(target_type="found", category="Earbuds")
    res_soft = search_by_attributes(test_db, req_soft)
    assert len(res_soft.matches) >= 1
    # Earbuds should rank #1 with high score
    assert res_soft.matches[0].report_id == rep_earbuds.id
    assert res_soft.matches[0].match_score >= 70.0
    # Incompatible charger (< 30% score) must not be returned in matches
    assert not any(m.report_id == rep_charger.id for m in res_soft.matches)

    # Strict search with category hard filter
    req_strict = AttributeFilterRequest(
        target_type="found", category="Earbuds",
        hard_filters=["category"],
    )
    res_strict = search_by_attributes(test_db, req_strict)
    # Charger (< 0.50 compat) and Neckband (< 0.50 compat) must be excluded
    matched_ids = [m.report_id for m in res_strict.matches]
    assert rep_earbuds.id in matched_ids
    assert rep_charger.id not in matched_ids
    assert rep_neckband.id not in matched_ids


def test_scenario_j_honest_explanations_no_false_color_or_shape():
    """Test J: Incompatible object does not get shape/size/color match reasons."""
    earbuds = ItemAttributes(
        category="Earbuds", primary_color="White", shape="Oval", size_category="Small"
    )
    charger = ItemAttributes(
        category="Charger", primary_color="White", shape="Oval", size_category="Small"
    )
    score, meta, explanation = compare_attributes(
        earbuds, charger,
        canonical_type1="audio.earbuds",
        canonical_type2="power.charger",
    )
    # Category is incompatible (0.0 < 0.30)
    assert meta["category_compatibility"] == 0.0
    # Because category is incompatible, shape and size should NOT be added as match reasons
    assert not any("Matching shape" in r for r in explanation.reasons)
    assert not any("Compatible size" in r for r in explanation.reasons)

