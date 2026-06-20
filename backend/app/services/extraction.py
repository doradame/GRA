import asyncio
import json
from typing import Any, Dict, List, Tuple
import logging
from openai import AsyncOpenAI, BadRequestError
from app.core.config import get_settings
from app.core.retry import openai_transient, retry_async
from app.services.api_usage import increment_extraction_calls
from app.services.entity_ids import canonical_entity_id

logger = logging.getLogger(__name__)
settings = get_settings()
_JSON_SCHEMA_SUPPORTED: bool | None = None

EXTRACTION_SCHEMA = {
    "name": "knowledge_graph_extraction",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "type": {"type": "string"},
                    },
                    "required": ["id", "name", "type"],
                },
            },
            "relations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_id": {"type": "string"},
                        "target_id": {"type": "string"},
                        "type": {"type": "string"},
                        "properties": {"type": "object"},
                    },
                    "required": ["source_id", "target_id", "type", "properties"],
                },
            },
        },
        "required": ["entities", "relations"],
    },
    "strict": True,
}

EXTRACTION_PROMPT = """
Sei un assistente esperto in estrazione di conoscenza da documenti.
Dal seguente testo estrai:
1. Entità rilevanti (persone, organizzazioni, prodotti, concetti, regole, requisiti, rischi, date, numeri, ecc.)
2. Relazioni significative tra queste entità (es. "richiede", "esclude", "include", "si riferisce a", "limita", "dipende da", "è parte di")

Regole:
- Usa ID temporanei stabili dentro questa risposta per collegare relazioni a entità.
- Non inventare entità non presenti o non chiaramente implicate dal testo.
- Mantieni nomi entità brevi e canonici.

Testo:
---
{text}
---
"""

RELATION_PROMPT = """
Sei un assistente esperto in estrazione di relazioni da documenti.
Dato il seguente testo e l'elenco delle entità già identificate, trova le relazioni logiche significative tra le entità.

Regole:
- Usa ESATTAMENTE gli ID forniti per source_id e target_id.
- Non inventare entità non presenti nell'elenco.
- Le relazioni devono essere chiaramente implicate dal testo.
- Mantieni i nomi delle relazioni brevi e in forma verbale (es. "richiede", "dipende_da", "include", "limita", "si_riferisce_a").

Entità:
{entities}

Testo:
---
{text}
---

Restituisci solo JSON valido con questa forma esatta:
{"relations":[{"source_id":"...","target_id":"...","type":"...","properties":{}}]}
"""


def _safe_parse_json(text: str) -> Dict[str, Any] | None:
    text = text.strip()
    # try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # extract first JSON object
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    logger.warning("Failed to parse LLM JSON extraction response")
    return None


def _normalize_relations(data: Dict[str, Any], valid_ids: set[str]) -> List[Dict[str, Any]]:
    """Normalizza e filtra le relazioni usando solo gli ID entità validi."""
    if not isinstance(data, dict):
        return []

    relations: List[Dict[str, Any]] = []
    seen_relations: set[tuple[str, str, str]] = set()
    raw_relations = data.get("relations", [])
    if not isinstance(raw_relations, list):
        logger.warning("LLM extraction relations field is not a list: %s", type(raw_relations).__name__)
        raw_relations = []

    for raw in raw_relations:
        if not isinstance(raw, dict):
            logger.debug("Skipping malformed extracted relation: %r", raw)
            continue
        source_id = str(raw.get("source_id", ""))
        target_id = str(raw.get("target_id", ""))
        relation_type = str(raw.get("type", "RELATED_TO")).strip() or "RELATED_TO"
        if source_id not in valid_ids or target_id not in valid_ids or source_id == target_id:
            continue
        key = (source_id, target_id, relation_type.casefold())
        if key in seen_relations:
            continue
        seen_relations.add(key)
        properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        relations.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "type": relation_type,
                "properties": properties,
            }
        )

    return relations


def _normalize_extraction(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Normalizza una risposta LLM con entità + relazioni (modalità legacy)."""
    if not isinstance(data, dict):
        logger.warning("LLM extraction response is not a JSON object: %s", type(data).__name__)
        return {"entities": [], "relations": []}

    entities: List[Dict[str, Any]] = []
    id_map: Dict[str, str] = {}
    seen_entities: set[str] = set()

    raw_entities = data.get("entities", [])
    if isinstance(raw_entities, dict):
        raw_entities = list(raw_entities.values())
    if not isinstance(raw_entities, list):
        logger.warning("LLM extraction entities field is not a list: %s", type(raw_entities).__name__)
        raw_entities = []

    for raw in raw_entities:
        if isinstance(raw, str):
            raw = {"name": raw, "type": "Unknown"}
        if not isinstance(raw, dict):
            logger.debug("Skipping malformed extracted entity: %r", raw)
            continue
        name = str(raw.get("name", "")).strip()
        entity_type = str(raw.get("type", "Unknown")).strip() or "Unknown"
        if not name:
            continue
        canonical_id = canonical_entity_id(name, entity_type)
        raw_id = str(raw.get("id", canonical_id))
        id_map[raw_id] = canonical_id
        if canonical_id in seen_entities:
            continue
        seen_entities.add(canonical_id)
        entities.append({"id": canonical_id, "name": name, "type": entity_type})

    # Mappa gli ID temporanei del LLM agli ID canonici nelle relazioni.
    valid_ids = {entity["id"] for entity in entities}
    raw_relations = data.get("relations", [])
    if not isinstance(raw_relations, list):
        logger.warning("LLM extraction relations field is not a list: %s", type(raw_relations).__name__)
        raw_relations = []

    normalized_relations: List[Dict[str, Any]] = []
    seen_relations: set[tuple[str, str, str]] = set()
    for raw in raw_relations:
        if not isinstance(raw, dict):
            logger.debug("Skipping malformed extracted relation: %r", raw)
            continue
        source_id = id_map.get(str(raw.get("source_id")), str(raw.get("source_id", "")))
        target_id = id_map.get(str(raw.get("target_id")), str(raw.get("target_id", "")))
        relation_type = str(raw.get("type", "RELATED_TO")).strip() or "RELATED_TO"
        if source_id not in valid_ids or target_id not in valid_ids or source_id == target_id:
            continue
        key = (source_id, target_id, relation_type.casefold())
        if key in seen_relations:
            continue
        seen_relations.add(key)
        properties = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        normalized_relations.append(
            {
                "source_id": source_id,
                "target_id": target_id,
                "type": relation_type,
                "properties": properties,
            }
        )

    return {"entities": entities, "relations": normalized_relations}


async def extract_relations(chunk_text: str, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Estrae le relazioni per un singolo chunk (crea e chiude il proprio client OpenAI).

    Mantenuto per compatibilita; il path di ingestion usa `extract_relations_batch`
    (concorrente, client condiviso). In caso di fallimento LLM ritorna [].
    """
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return []
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        return await _extract_relations_with_client(client, chunk_text, entities)
    finally:
        await client.close()


async def extract_relations_batch(
    items: List[Tuple[str, List[Dict[str, Any]]]],
) -> List[List[Dict[str, Any]]]:
    """Estrae le relazioni per tutti i chunk in concorrenza (client condiviso + semaphore).

    `items` e una lista di (chunk_text, entities); ritorna le relazioni di ciascuno nello
    stesso ordine. Una chiamata LLM per chunk con concorrenza limitata da
    settings.extraction_concurrency (stesso pattern di contextual_chunking). I chunk con
    meno di 2 entita, in modalita test, o su errore LLM persistente contribuiscono con []
    senza abortire il batch.
    """
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return [[] for _ in items]

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    semaphore = asyncio.Semaphore(max(1, settings.extraction_concurrency))
    try:

        async def _one(chunk_text: str, entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            async with semaphore:
                return await _extract_relations_with_client(client, chunk_text, entities)

        return await asyncio.gather(*[_one(ct, ents) for ct, ents in items])
    finally:
        await client.close()


async def _extract_relations_with_client(
    client: AsyncOpenAI,
    chunk_text: str,
    entities: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Estrae le relazioni per un chunk usando un client OpenAI gia aperto (condivisibile).

    Degradazione resiliente: su errore LLM (anche dopo i retry) ritorna [] invece di
    propagare, cosi un chunk problematico non abortisce l'intera ingestion.
    """
    if len(entities) < 2:
        logger.debug("[extraction] Not enough entities (%s) to extract relations", len(entities))
        return []

    valid_ids = {entity["id"] for entity in entities}
    entities_text = "\n".join(
        f'- ID: {entity["id"]}, Nome: {entity["name"]}, Tipo: {entity["type"]}'
        for entity in entities
    )
    prompt = RELATION_PROMPT.replace("{entities}", entities_text).replace("{text}", chunk_text[:8000])

    try:
        response = await retry_async(
            lambda: client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": "Estrai solo relazioni verificabili dal testo."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            ),
            retry_on=openai_transient(),
            what="relation extraction",
        )
    except Exception as exc:
        logger.warning("[extraction] Relation extraction LLM call failed after retries: %s", exc)
        return []

    tokens = 0
    if response.usage:
        tokens = response.usage.total_tokens or 0
    increment_extraction_calls(tokens=tokens)
    data = _safe_parse_json(response.choices[0].message.content)
    if data is None:
        return []
    return _normalize_relations(data, valid_ids)


async def extract_entities_relations(text: str) -> Dict[str, List[Dict[str, Any]]]:
    """Estrae entità e relazioni in un'unica chiamata LLM (modalità legacy).

    Mantenuto per retrocompatibilità e per eventuali tool che non usano GLiNER.
    """
    global _JSON_SCHEMA_SUPPORTED

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return {"entities": [], "relations": []}

    # Create a fresh client bound to the current event loop.
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    prompt = EXTRACTION_PROMPT.replace("{text}", text[:8000])
    try:
        response = None
        if _JSON_SCHEMA_SUPPORTED is not False:
            try:
                response = await client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[
                        {"role": "system", "content": "Estrai solo conoscenza verificabile dal testo."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    response_format={"type": "json_schema", "json_schema": EXTRACTION_SCHEMA},
                )
                _JSON_SCHEMA_SUPPORTED = True
            except BadRequestError:
                _JSON_SCHEMA_SUPPORTED = False
                logger.warning("Structured extraction unsupported by model/API; using json_object mode for this worker")

        if response is None:
            response = await client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Restituisci solo JSON valido con questa forma esatta: "
                            '{"entities":[{"id":"...","name":"...","type":"..."}],'
                            '"relations":[{"source_id":"...","target_id":"...","type":"...","properties":{}}]}.'
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
        # Track API usage (one call per chunk, token usage from response if available).
        tokens = 0
        if response.usage:
            tokens = response.usage.total_tokens or 0
        increment_extraction_calls(tokens=tokens)
        content = response.choices[0].message.content
        data = _safe_parse_json(content)
        if data is None:
            return {"entities": [], "relations": []}

        return _normalize_extraction(data)
    finally:
        await client.close()
