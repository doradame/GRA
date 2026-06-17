from typing import Iterable, Sequence


def precision_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    if k <= 0:
        return 0.0
    relevant = set(relevant_ids)
    if not relevant:
        return 0.0
    top_k = retrieved_ids[:k]
    return len([item for item in top_k if item in relevant]) / k


def recall_at_k(retrieved_ids: Sequence[str], relevant_ids: Iterable[str], k: int) -> float:
    relevant = set(relevant_ids)
    if not relevant or k <= 0:
        return 0.0
    top_k = set(retrieved_ids[:k])
    return len(top_k & relevant) / len(relevant)


def document_coverage_at_k(retrieved_document_ids: Sequence[str], expected_document_ids: Iterable[str], k: int) -> float:
    expected = set(expected_document_ids)
    if not expected or k <= 0:
        return 0.0
    retrieved = set(retrieved_document_ids[:k])
    return len(retrieved & expected) / len(expected)


def mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
