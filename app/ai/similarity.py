
import math


def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """Calculate cosine similarity between two embedding vectors."""

    if not vector_a or not vector_b:
        raise ValueError("Embedding vectors cannot be empty.")

    if len(vector_a) != len(vector_b):
        raise ValueError("Embedding dimensions must match.")

    try:
        if not all(
            math.isfinite(value)
            for value in (*vector_a, *vector_b)
        ):
            raise ValueError(
                "Embedding values must be finite numbers."
            )

        dot_product = sum(
            a * b for a, b in zip(vector_a, vector_b)
        )

        norm_a = math.sqrt(sum(a * a for a in vector_a))
        norm_b = math.sqrt(sum(b * b for b in vector_b))

        if norm_a == 0.0 or norm_b == 0.0:
            raise ValueError(
                "Cannot compare zero-length vectors."
            )

        similarity = dot_product / (norm_a * norm_b)

    except (TypeError, OverflowError) as exc:
        raise ValueError(
            "Embedding vectors must contain valid finite numbers."
        ) from exc

    return max(-1.0, min(1.0, similarity))


def normalized_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """Map cosine similarity from [-1, 1] to [0, 1]."""

    similarity = cosine_similarity(vector_a, vector_b)
    return (similarity + 1.0) / 2.0
