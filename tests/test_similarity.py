import math

import pytest

from app.ai.similarity import (
    cosine_similarity,
    normalized_similarity,
)


def test_identical_vectors_have_similarity_one():
    vector = [1.0, 2.0, 3.0]

    assert cosine_similarity(vector, vector) == pytest.approx(1.0)


def test_opposite_vectors_have_similarity_minus_one():
    assert cosine_similarity(
        [1.0, 0.0],
        [-1.0, 0.0],
    ) == pytest.approx(-1.0)


def test_perpendicular_vectors_have_similarity_zero():
    assert cosine_similarity(
        [1.0, 0.0],
        [0.0, 1.0],
    ) == pytest.approx(0.0)


def test_similarity_is_independent_of_positive_magnitude():
    assert cosine_similarity(
        [1.0, 2.0],
        [10.0, 20.0],
    ) == pytest.approx(1.0)


def test_normalized_similarity_maps_one_to_one():
    assert normalized_similarity(
        [1.0, 0.0],
        [1.0, 0.0],
    ) == pytest.approx(1.0)


def test_normalized_similarity_maps_zero_to_half():
    assert normalized_similarity(
        [1.0, 0.0],
        [0.0, 1.0],
    ) == pytest.approx(0.5)


def test_normalized_similarity_maps_minus_one_to_zero():
    assert normalized_similarity(
        [1.0, 0.0],
        [-1.0, 0.0],
    ) == pytest.approx(0.0)


def test_empty_vectors_are_rejected():
    with pytest.raises(ValueError, match="cannot be empty"):
        cosine_similarity([], [])


def test_different_dimensions_are_rejected():
    with pytest.raises(ValueError, match="dimensions must match"):
        cosine_similarity([1.0, 2.0], [1.0])


@pytest.mark.parametrize(
    "invalid_value",
    [math.nan, math.inf, -math.inf],
)
def test_non_finite_values_are_rejected(invalid_value):
    with pytest.raises(ValueError, match="finite"):
        cosine_similarity([1.0, invalid_value], [1.0, 2.0])


def test_zero_vector_is_rejected():
    with pytest.raises(ValueError, match="zero-length"):
        cosine_similarity([0.0, 0.0], [1.0, 2.0])
