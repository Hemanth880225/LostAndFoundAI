
import math


def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """Calculate cosine similarity between two vectors."""
    if len(vector_a) != len(vector_b):
        raise ValueError(
            "Embedding dimensions must match."
        )

    dot_product = sum(
        a * b for a, b in zip(vector_a, vector_b)
    )

    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    if norm_a == 0 or norm_b == 0:
        raise ValueError(
            "Cannot compare zero-length vectors."
        )

    similarity = dot_product / (norm_a * norm_b)

    return max(-1.0, min(1.0, similarity))


def normalized_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """Map cosine similarity from [-1, 1] into [0, 1]."""
    return (cosine_similarity(vector_a, vector_b) + 1.0) / 2.0
