"""Evaluation suite for benchmarking attribute-aware AI ranking quality against labelled pairs.

Calculates:
- Precision@K (P@1, P@3, P@5)
- Recall@K (R@1, R@3, R@5)
- Mean Reciprocal Rank (MRR)
"""

from typing import Any, Dict, List, Set, Tuple
from sqlalchemy.orm import Session

from app.db.models import ItemReport
from app.extensions.attribute_matching.schemas import AttributeFilterRequest
from app.extensions.attribute_matching.service import search_by_attributes


def precision_at_k(ground_truth_ids: Set[int], retrieved_ranking_ids: List[int], k: int) -> float:
    """Fraction of relevant reports among the top-k retrieved reports."""
    if k <= 0 or not retrieved_ranking_ids:
        return 0.0
    top_k = retrieved_ranking_ids[:k]
    relevant_in_top_k = sum(1 for item_id in top_k if item_id in ground_truth_ids)
    return relevant_in_top_k / float(k)


def recall_at_k(ground_truth_ids: Set[int], retrieved_ranking_ids: List[int], k: int) -> float:
    """Fraction of relevant reports retrieved in the top-k over all ground-truth relevant reports."""
    if not ground_truth_ids:
        return 1.0
    top_k = retrieved_ranking_ids[:k]
    relevant_in_top_k = sum(1 for item_id in top_k if item_id in ground_truth_ids)
    return relevant_in_top_k / float(len(ground_truth_ids))


def reciprocal_rank(ground_truth_ids: Set[int], retrieved_ranking_ids: List[int]) -> float:
    """Reciprocal of the 1-based rank of the first relevant retrieved report."""
    for rank, item_id in enumerate(retrieved_ranking_ids, start=1):
        if item_id in ground_truth_ids:
            return 1.0 / float(rank)
    return 0.0


def mean_reciprocal_rank(
    ground_truth_per_query: Dict[str, Set[int]],
    rankings_per_query: Dict[str, List[int]],
) -> float:
    """Mean Reciprocal Rank across multiple queries."""
    if not ground_truth_per_query:
        return 0.0
    rr_scores = [
        reciprocal_rank(ground_truth_per_query[q], rankings_per_query.get(q, []))
        for q in ground_truth_per_query
    ]
    return sum(rr_scores) / float(len(rr_scores))


def evaluate_attribute_search_quality(
    db: Session,
    labelled_queries: List[Dict[str, Any]],
) -> Dict[str, float]:
    """
    Evaluate ranking quality across a suite of labelled query-target pairs.

    Each entry in labelled_queries:
    {
        "query_id": str,
        "request": AttributeFilterRequest,
        "target_report_ids": Set[int],
    }
    """
    ground_truth_map: Dict[str, Set[int]] = {}
    rankings_map: Dict[str, List[int]] = {}
    p1_scores = []
    p3_scores = []
    r3_scores = []

    for item in labelled_queries:
        q_id = item["query_id"]
        req: AttributeFilterRequest = item["request"]
        targets: Set[int] = set(item["target_report_ids"])

        res = search_by_attributes(db=db, request=req)
        retrieved_ids = [m.report_id for m in res.matches]

        ground_truth_map[q_id] = targets
        rankings_map[q_id] = retrieved_ids

        p1_scores.append(precision_at_k(targets, retrieved_ids, k=1))
        p3_scores.append(precision_at_k(targets, retrieved_ids, k=3))
        r3_scores.append(recall_at_k(targets, retrieved_ids, k=3))

    mrr = mean_reciprocal_rank(ground_truth_map, rankings_map)
    avg_p1 = sum(p1_scores) / float(len(p1_scores)) if p1_scores else 0.0
    avg_p3 = sum(p3_scores) / float(len(p3_scores)) if p3_scores else 0.0
    avg_r3 = sum(r3_scores) / float(len(r3_scores)) if r3_scores else 0.0

    return {
        "mrr": round(mrr, 4),
        "precision_at_1": round(avg_p1, 4),
        "precision_at_3": round(avg_p3, 4),
        "recall_at_3": round(avg_r3, 4),
        "total_queries_evaluated": len(labelled_queries),
    }
