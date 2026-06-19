import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Cache lazy del modello cross-encoder all'interno del processo backend.
_model = None
_load_failed = False


def _get_model() -> Any:
    """Carica e cache il modello cross-encoder in modo lazy. None se disabilitato o non disponibile."""
    global _model, _load_failed
    if _model is not None:
        return _model
    if _load_failed:
        return None

    settings = get_settings()
    if not settings.enable_reranker:
        return None

    try:
        from sentence_transformers import CrossEncoder

        logger.info("[reranker] Loading cross-encoder model: %s", settings.reranker_model)
        _model = CrossEncoder(settings.reranker_model, max_length=512)
        logger.info("[reranker] Cross-encoder model ready")
    except Exception:
        logger.exception("[reranker] Failed to load cross-encoder model; callers should fall back to lexical rerank")
        _load_failed = True
        _model = None
    return _model


def rerank_cross_encoder(query: str, results: list[dict]) -> list[dict] | None:
    """Reranka `results` (ognuno con un `payload.text`) con un cross-encoder locale.

    Restituisce None se il modello non è disponibile, cosi' il chiamante può
    usare un fallback piu' economico (es. rerank lessicale) invece di fallire.
    """
    if not results:
        return results

    model = _get_model()
    if model is None:
        return None

    pairs = [(query, str(r.get("payload", {}).get("text", ""))) for r in results]
    try:
        scores = model.predict(pairs)
    except Exception:
        logger.exception("[reranker] Cross-encoder inference failed; falling back to lexical rerank")
        return None

    reranked = []
    for result, score in zip(results, scores):
        enriched = dict(result)
        enriched["hybrid_score"] = float(score)
        enriched["rerank_score"] = float(score)
        reranked.append(enriched)
    return sorted(reranked, key=lambda item: item["hybrid_score"], reverse=True)
