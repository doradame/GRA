from app.services.sparse_vectors import build_sparse_vector, tokenize_sparse


def test_tokenize_sparse_filters_short_tokens_and_stopwords():
    assert tokenize_sparse("The risk approval per policy X") == ["risk", "approval", "policy"]


def test_build_sparse_vector_is_deterministic_and_normalized():
    first = build_sparse_vector("risk risk approval")
    second = build_sparse_vector("risk risk approval")

    assert first.indices == second.indices
    assert first.values == second.values
    assert len(first.indices) == 2
    assert abs(sum(value * value for value in first.values) - 1.0) < 1e-9
