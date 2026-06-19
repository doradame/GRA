import app.services.sparse_vectors as sparse_vectors_module
from app.services.sparse_vectors import (
    build_query_sparse_vector,
    tokenize_sparse,
    weighted_sparse_vector,
)


def test_tokenize_sparse_filters_short_tokens_and_stopwords():
    assert tokenize_sparse("The risk approval per policy X") == ["risk", "approval", "policy"]


def test_weighted_sparse_vector_is_deterministic_and_normalized():
    tokens = tokenize_sparse("risk risk approval")
    vocab = {"risk": 1, "approval": 2}

    first = weighted_sparse_vector(tokens, vocab, global_df={}, total_chunks=10, avg_doc_len=5.0)
    second = weighted_sparse_vector(tokens, vocab, global_df={}, total_chunks=10, avg_doc_len=5.0)

    assert first.indices == second.indices
    assert first.values == second.values
    assert len(first.indices) == 2
    assert abs(sum(value * value for value in first.values) - 1.0) < 1e-9


def test_weighted_sparse_vector_skips_terms_outside_vocabulary():
    tokens = tokenize_sparse("risk approval unknown")
    vocab = {"risk": 1, "approval": 2}  # "unknown" non registrato

    vector = weighted_sparse_vector(tokens, vocab, global_df={}, total_chunks=10, avg_doc_len=5.0)

    assert set(vector.indices) == {1, 2}


def test_weighted_sparse_vector_gives_rarer_terms_more_weight():
    # Stesso testo, stessa frequenza per entrambi i termini: solo la document frequency cambia.
    tokens = tokenize_sparse("risk approval")
    vocab = {"risk": 1, "approval": 2}
    # "risk" è raro nel corpus (df=1 su 100 chunk), "approval" è comunissimo (df=90 su 100).
    global_df = {1: 1, 2: 90}

    vector = weighted_sparse_vector(tokens, vocab, global_df=global_df, total_chunks=100, avg_doc_len=2.0)

    weight_by_index = dict(zip(vector.indices, vector.values))
    assert weight_by_index[1] > weight_by_index[2]


def test_build_query_sparse_vector_uses_cached_vocab_and_global_stats(monkeypatch):
    monkeypatch.setattr(
        sparse_vectors_module, "get_term_ids_cached", lambda terms: {"risk": 1, "approval": 2}
    )
    monkeypatch.setattr(
        sparse_vectors_module,
        "get_global_stats_snapshot",
        lambda term_ids: ({1: 5, 2: 50}, 100, 8.0),
    )

    vector = build_query_sparse_vector("risk approval")

    assert set(vector.indices) == {1, 2}
    assert abs(sum(v * v for v in vector.values) - 1.0) < 1e-9
