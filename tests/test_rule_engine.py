from datetime import date
from types import SimpleNamespace

from app.ai.rule_engine import (
    backward_chaining,
    evaluate_match,
    find_evidence_combination,
    forward_chaining,
)


def make_report(**overrides):
    values = {
        "category": "electronics",
        "color": "black",
        "event_date": date(2026, 10, 10),
        "latitude": 18.5204,
        "longitude": 73.8567,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_forward_chaining_derives_same_category():
    facts = forward_chaining({"category_match"})

    assert "same_category" in facts


def test_forward_chaining_derives_plausible_match_from_text():
    facts = forward_chaining(
        {"category_match", "text_similar"}
    )

    assert "plausible_match" in facts


def test_forward_chaining_derives_context_from_date_and_location():
    facts = forward_chaining(
        {"date_close", "location_supported"}
    )

    assert "context_supported" in facts


def test_backward_chaining_proves_plausible_match():
    assert backward_chaining(
        "plausible_match",
        {"category_match", "text_similar"},
    ) is True


def test_backward_chaining_rejects_insufficient_evidence():
    assert backward_chaining(
        "plausible_match",
        {"category_match"},
    ) is False


def test_backtracking_finds_a_valid_evidence_combination():
    result = find_evidence_combination(
        evidence=[
            "category_match",
            "text_similar",
            "color_match",
        ],
        required_count=2,
        target_goal="plausible_match",
    )

    assert result is not None
    assert len(result) >= 2
    assert "plausible_match" in forward_chaining(set(result))


def test_backtracking_returns_none_when_goal_cannot_be_proved():
    result = find_evidence_combination(
        evidence=["color_match", "date_close"],
        required_count=2,
        target_goal="plausible_match",
    )

    assert result is None


def test_evaluate_match_accepts_matching_category_and_text():
    lost = make_report()
    found = make_report()
    components = {"text": 0.80, "location": 0.90}

    result = evaluate_match(lost, found, components)

    assert result["plausible_match"] is True
    assert result["backward_chaining_goal_proven"] is True
    assert result["backtracking_evidence"] is not None


def test_evaluate_match_rejects_different_categories():
    lost = make_report(category="electronics")
    found = make_report(category="clothing")
    components = {"text": 0.95, "location": 0.90}

    result = evaluate_match(lost, found, components)

    assert result["plausible_match"] is False
