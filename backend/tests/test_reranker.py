from types import SimpleNamespace

import app.services.reranker as reranker


def test_rerank_cross_encoder_returns_input_for_empty_results(monkeypatch):
    monkeypatch.setattr(reranker, "_model", None)
    monkeypatch.setattr(reranker, "_load_failed", False)

    assert reranker.rerank_cross_encoder("query", []) == []


def test_rerank_cross_encoder_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(reranker, "_model", None)
    monkeypatch.setattr(reranker, "_load_failed", False)
    monkeypatch.setattr(
        reranker,
        "get_settings",
        lambda: SimpleNamespace(enable_reranker=False, reranker_model="unused"),
    )

    result = reranker.rerank_cross_encoder("query", [{"score": 0.5, "payload": {"text": "foo"}}])

    assert result is None


def test_rerank_cross_encoder_falls_back_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(reranker, "_model", None)
    monkeypatch.setattr(reranker, "_load_failed", True)  # simula un fallimento di caricamento precedente
    monkeypatch.setattr(
        reranker,
        "get_settings",
        lambda: SimpleNamespace(enable_reranker=True, reranker_model="unused"),
    )

    result = reranker.rerank_cross_encoder("query", [{"score": 0.5, "payload": {"text": "foo"}}])

    assert result is None


def test_rerank_cross_encoder_sorts_by_score_when_model_available(monkeypatch):
    monkeypatch.setattr(reranker, "_load_failed", False)

    class _FakeCrossEncoder:
        def predict(self, pairs):
            return [0.1 if "irrelevant" in text else 0.9 for _, text in pairs]

    monkeypatch.setattr(reranker, "_model", _FakeCrossEncoder())

    results = [
        {"score": 0.5, "payload": {"text": "irrelevant filler text"}},
        {"score": 0.4, "payload": {"text": "highly relevant passage"}},
    ]

    reranked = reranker.rerank_cross_encoder("query", results)

    assert reranked[0]["payload"]["text"] == "highly relevant passage"
    assert reranked[0]["rerank_score"] > reranked[1]["rerank_score"]


def test_rerank_cross_encoder_falls_back_on_inference_error(monkeypatch):
    monkeypatch.setattr(reranker, "_load_failed", False)

    class _BoomCrossEncoder:
        def predict(self, pairs):
            raise RuntimeError("inference blew up")

    monkeypatch.setattr(reranker, "_model", _BoomCrossEncoder())

    result = reranker.rerank_cross_encoder("query", [{"score": 0.5, "payload": {"text": "foo"}}])

    assert result is None
