from app.services.retrieval_metrics import (
    document_coverage_at_k,
    mean,
    precision_at_k,
    recall_at_k,
)


def test_precision_and_recall_at_k():
    retrieved = ["a", "b", "c", "d"]
    relevant = {"b", "d", "e"}

    assert precision_at_k(retrieved, relevant, 2) == 0.5
    assert recall_at_k(retrieved, relevant, 4) == 2 / 3


def test_document_coverage_and_mean():
    assert document_coverage_at_k(["doc-1", "doc-2"], {"doc-2", "doc-3"}, 2) == 0.5
    assert mean([0.5, 1.0]) == 0.75
    assert mean([]) == 0.0
