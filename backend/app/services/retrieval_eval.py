import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.retrieval_metrics import (
    document_coverage_at_k,
    mean,
    precision_at_k,
    recall_at_k,
)


@dataclass
class RetrievalEvalResult:
    cases: int
    precision_at_k: float
    recall_at_k: float
    document_coverage_at_k: float


def evaluate_retrieval_cases(cases: list[dict[str, Any]], k: int = 5) -> RetrievalEvalResult:
    precisions = []
    recalls = []
    coverages = []

    for case in cases:
        retrieved_chunk_ids = case.get("retrieved_chunk_ids", [])
        relevant_chunk_ids = case.get("relevant_chunk_ids", [])
        retrieved_document_ids = case.get("retrieved_document_ids", [])
        expected_document_ids = case.get("expected_document_ids", [])

        precisions.append(precision_at_k(retrieved_chunk_ids, relevant_chunk_ids, k))
        recalls.append(recall_at_k(retrieved_chunk_ids, relevant_chunk_ids, k))
        coverages.append(document_coverage_at_k(retrieved_document_ids, expected_document_ids, k))

    return RetrievalEvalResult(
        cases=len(cases),
        precision_at_k=mean(precisions),
        recall_at_k=mean(recalls),
        document_coverage_at_k=mean(coverages),
    )


def evaluate_retrieval_file(path: str | Path, k: int = 5) -> RetrievalEvalResult:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) else data
    return evaluate_retrieval_cases(cases, k=k)
