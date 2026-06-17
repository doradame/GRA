from app.services.retrieval_eval import evaluate_retrieval_cases


def test_evaluate_retrieval_cases_aggregates_metrics():
    result = evaluate_retrieval_cases(
        [
            {
                "relevant_chunk_ids": ["a", "b"],
                "retrieved_chunk_ids": ["a", "x"],
                "expected_document_ids": ["doc-1"],
                "retrieved_document_ids": ["doc-1", "doc-2"],
            }
        ],
        k=2,
    )

    assert result.cases == 1
    assert result.precision_at_k == 0.5
    assert result.recall_at_k == 0.5
    assert result.document_coverage_at_k == 1.0
