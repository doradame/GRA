from app.services.rag_engine import _diversify_results, _extract_quote, _format_reference, _rerank_hybrid


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


def test_reference_and_quote_helpers_prefer_human_readable_metadata():
    payload = {
        "filename": "manuale.pdf",
        "page_start": 4,
        "page_end": 5,
        "char_start": 1200,
        "char_end": 1800,
        "document_page_count": 20,
        "section_title": "CONDIZIONI",
        "index": 2,
    }

    assert _format_reference(payload) == "manuale.pdf, pagine 4-5"
    assert _extract_quote("  Una frase   con spazi\nmultipli.  ") == "Una frase con spazi multipli."
