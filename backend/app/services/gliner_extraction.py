import logging
from typing import Any

from app.core.config import get_settings
from app.services.entity_ids import canonical_entity_id

logger = logging.getLogger(__name__)

# Cache lazy del modello GLiNER all'interno del processo worker.
_model = None


def _get_model() -> Any:
    """Carica e cache il modello GLiNER in modo lazy."""
    global _model
    if _model is not None:
        return _model

    settings = get_settings()
    try:
        from gliner import GLiNER
    except ImportError as exc:
        logger.exception("[gliner] GLiNER not installed: %s", exc)
        raise

    logger.info("[gliner] Loading model: %s", settings.gliner_model)
    _model = GLiNER.from_pretrained(settings.gliner_model)
    logger.info("[gliner] Model loaded successfully")
    return _model


def _default_labels() -> list[str]:
    """Restituisce le label di default dalla configurazione."""
    settings = get_settings()
    return [label.strip() for label in settings.gliner_labels.split(",") if label.strip()]


def extract_entities(
    text: str,
    labels: list[str] | None = None,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Estrae entità dal testo usando il modello GLiNER locale.

    Args:
        text: il testo da analizzare.
        labels: lista di tipi di entità da riconoscere. Se None, usa le label configurate.
        threshold: soglia di confidenza. Se None, usa gliner_threshold dalle settings.

    Returns:
        Lista di entità nel formato {"id": str, "name": str, "type": str}.
    """
    settings = get_settings()
    if not settings.enable_gliner:
        logger.debug("[gliner] GLiNER disabled by configuration")
        return []

    if not text or not text.strip():
        return []

    model = _get_model()
    labels = labels or _default_labels()
    threshold = threshold if threshold is not None else settings.gliner_threshold

    try:
        raw_entities = model.predict_entities(text, labels, threshold=threshold)
    except Exception as exc:
        logger.exception("[gliner] Extraction failed: %s", exc)
        return []

    entities: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_entities:
        name = str(item.get("text", "")).strip()
        entity_type = str(item.get("label", "Unknown")).strip() or "Unknown"
        if not name:
            continue

        entity_id = canonical_entity_id(name, entity_type)
        if entity_id in seen:
            continue
        seen.add(entity_id)

        entities.append(
            {
                "id": entity_id,
                "name": name,
                "type": entity_type,
            }
        )

    logger.debug("[gliner] Extracted %s entities from text of %s chars", len(entities), len(text))
    return entities
