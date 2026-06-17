from app.services.rag_engine import _diversify_results, _rerank_hybrid


def test_diversify_results_drops_near_duplicate_chunks():
    results = [
        {"score": 0.9, "payload": {"text": "Policy X requires approval from the risk team"}},
        {"score": 0.89, "payload": {"text": "Policy X requires approval from the risk team"}},
        {"score": 0.88, "payload": {"text": "Policy Y excludes expired contracts"}},
    ]

    diversified = _diversify_results(results)

    assert diversified == [results[0], results[2]]


def test_rerank_hybrid_adds_lexical_signal():
    results = [
        {"score": 0.8, "payload": {"text": "general policy overview"}},
        {"score": 0.79, "payload": {"text": "risk approval required for policy x"}},
    ]

    reranked = _rerank_hybrid("risk approval", results)

    assert reranked[0]["payload"]["text"] == "risk approval required for policy x"
    assert reranked[0]["lexical_score"] > reranked[1]["lexical_score"]
