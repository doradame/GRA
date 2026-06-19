import asyncio
import json
import logging
import re
from typing import Any, Dict, List

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.agent.state import CypherToolResult
from app.services.agent.tools.vector_tool import vector_tool
from app.services.graph_store import graph_store

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)
logger = logging.getLogger(__name__)


ALLOWED_CYPHER_TOKENS = {
    "MATCH", "RETURN", "WITH", "UNWIND", "CALL", "WHERE", "LIMIT",
    "OPTIONAL", "ORDER", "BY", "COUNT", "COLLECT", "AS", "DISTINCT",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "CASE", "WHEN", "THEN",
    "ELSE", "END", "TRUE", "FALSE", "CONTAINS", "STARTS", "ENDS",
    "TOLOWER", "TOUPPER", "TRIM", "LEFT", "RIGHT", "SUBSTRING",
    "APOC", "META", "CYPHER", "TYPE", "LABELS", "ID", "ELEMENTID",
}

DISALLOWED_CYPHER_TOKENS = {
    "CREATE", "DELETE", "DETACH", "SET", "REMOVE", "MERGE", "DROP",
}


SCHEMA_DESCRIPTION = """Schema del grafo Neo4j:

Nodi:
- :Document {id, filename, content_type, user_id}
- :Chunk {id, text, index, user_id}
- :Entity {id, name, type, normalized_name}
- :CommunitySummary {id, summary, created_at, updated_at}

Relazioni:
- (Chunk)-[:BELONGS_TO]->(Document)
- (Chunk)-[:MENTIONS]->(Entity)
- (Entity)-[:<TIPO_DINAMICO>]->(Entity)
- (Entity)-[:BELONGS_TO_COMMUNITY]->(CommunitySummary)

Regole per la query Cypher:
- Deve essere read-only (solo MATCH/RETURN/WITH/CALL/WHERE/LIMIT/OPTIONAL/ORDER BY/COUNT/COLLECT).
- Usa toLower(e.name) CONTAINS toLower($term) per match fuzzy sui nomi.
- Usa LIMIT per evitare risultati enormi.
- Non usare CREATE, DELETE, SET, MERGE, DROP o altre operazioni di scrittura.

Rispondi SOLO con JSON:
{"cypher": "...", "parameters": {"term": "..."}}
"""


def _extract_cypher_tokens(cypher: str) -> set[str]:
    # Rimuove stringhe tra apici e prende token alfanumerici maiuscoli
    no_strings = re.sub(r"'[^']*'|\"[^\"]*\"", "", cypher)
    return {token.upper() for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", no_strings)}


def validate_cypher(cypher: str) -> bool:
    if not cypher or not cypher.strip().upper().startswith("MATCH"):
        return False
    tokens = _extract_cypher_tokens(cypher)
    if tokens & DISALLOWED_CYPHER_TOKENS:
        logger.warning("[cypher_tool] Token non consentiti rilevati: %s", tokens & DISALLOWED_CYPHER_TOKENS)
        return False
    return True


async def generate_cypher(query: str, previous_error: str | None = None) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SCHEMA_DESCRIPTION},
        {"role": "user", "content": f"Domanda utente: {query}"},
    ]
    if previous_error:
        messages.append({"role": "user", "content": f"La query precedente ha dato errore: {previous_error}. Correggila."})

    response = await client.chat.completions.create(
        model=settings.cypher_model,
        messages=messages,
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return json.loads(content)


def _run_cypher(cypher: str, parameters: Dict[str, Any] | None = None) -> List[dict]:
    parameters = parameters or {}
    with graph_store.driver.session() as session:
        result = session.run(cypher, parameters)
        return [record.data() for record in result]


def _summarize_results(query: str, results: List[dict]) -> str:
    if not results:
        return "Nessun risultato trovato nel grafo per questa domanda."
    # Estrae i valori come testo semplice per il riassunto
    lines = []
    for i, row in enumerate(results[:20]):
        line = ", ".join(f"{k}: {v}" for k, v in row.items())
        lines.append(f"- {line}")
    return "\n".join(lines)


async def cypher_tool(query: str) -> CypherToolResult:
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return CypherToolResult(
            cypher="",
            results=[],
            summary="[MODALITÀ TEST] Text2Cypher non disponibile senza chiave OpenAI valida.",
            error="missing openai key",
        )

    max_retries = settings.agent_cypher_max_retries
    last_error = None
    cypher = ""
    parameters = {}

    for attempt in range(max_retries + 1):
        try:
            generated = await generate_cypher(query, previous_error=last_error)
            cypher = generated.get("cypher", "").strip()
            parameters = generated.get("parameters") or {}
            if not validate_cypher(cypher):
                last_error = "Query Cypher non valida o contiene operazioni di scrittura."
                logger.warning("[cypher_tool] %s", last_error)
                continue
            results = _run_cypher(cypher, parameters)
            summary = _summarize_results(query, results)
            return CypherToolResult(cypher=cypher, results=results, summary=summary, error=None)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("[cypher_tool] Tentativo %s fallito: %s", attempt + 1, last_error)

    return CypherToolResult(
        cypher=cypher,
        results=[],
        summary="Non sono riuscito a eseguire la query sul grafo.",
        error=last_error or "unknown error",
    )


async def run_cypher_tool(state) -> dict:
    """Esegue il path "relational" eseguendo SEMPRE anche una ricerca vettoriale in parallelo.

    Una query Cypher generata dall'LLM può "riuscire" (nessun errore, un risultato) pur essendo
    semanticamente sbagliata (es. cercare il termine della domanda come nome di entità). Avere
    sempre il grounding vettoriale come rete di sicurezza evita che il sintetizzatore costruisca
    una risposta solo su un fatto spurio dal grafo. _build_context_from_state/_collect_citations
    (in nodes.py) combinano già vector_results + cypher_results se entrambi sono presenti.
    """
    query = state.get("user_query", "")
    cypher_result, vector_result = await asyncio.gather(
        cypher_tool(query=query),
        vector_tool(query=query, user_id=state.get("user_id")),
    )
    return {
        "cypher_results": cypher_result,
        "vector_results": vector_result,
    }
