from datetime import date
from types import SimpleNamespace

import pytest

from app.ai.ranking import (
    attribute_similarity,
    location_similarity,
    normalize_text,
    text_similarity,
    time_similarity,
)


def make_report(**overrides):
    values = {
        "category": "electronics",
        "brand": "Samsung",
        "model": "Galaxy S23",
        "color": "black",
        "latitude": 18.5204,
        "longitude": 73.8567,
        "event_date": date(2026, 10, 10),
        "item_name": "Black phone",
        "description": "Samsung smartphone",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_normalize_text_ignores_case_and_extra_spaces():
    assert normalize_text("  BLACK   Phone ") == "black phone"


def test_normalize_text_preserves_unicode():
    assert normalize_text("Café फोन") == "café फोन"


def test_empty_text_has_zero_similarity():
    assert text_similarity("", "black phone") == 0.0


def test_identical_text_has_similarity_one():
    assert text_similarity("Black phone", "black phone") == pytest.approx(1.0)


def test_matching_attributes_have_high_similarity():
    report = make_report()
    assert attribute_similarity(report, report) == pytest.approx(1.0)


def test_missing_attributes_do_not_crash():
    lost = make_report(brand=None, model=None, color=None)
    found = make_report(brand=None, model=None, color=None)

    assert attribute_similarity(lost, found) == pytest.approx(1.0)


def test_location_is_unavailable_without_coordinates():
    lost = make_report(latitude=None, longitude=None)
    found = make_report()

    assert location_similarity(lost, found) is None


def test_same_coordinates_have_similarity_one():
    report = make_report()

    assert location_similarity(report, report) == pytest.approx(1.0)


def test_time_similarity_is_one_for_same_date():
    event_date = date(2026, 10, 10)

    assert time_similarity(event_date, event_date) == pytest.approx(1.0)


def test_time_similarity_decreases_with_date_gap():
    near_date = date(2026, 10, 11)
    far_date = date(2026, 10, 20)

    assert time_similarity(
        date(2026, 10, 10), near_date
    ) > time_similarity(date(2026, 10, 10), far_date)


def test_time_is_unavailable_when_date_is_missing():
    assert time_similarity(None, date(2026, 10, 10)) is None
