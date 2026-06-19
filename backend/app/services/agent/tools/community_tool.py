import logging
from typing import List, Set

from app.core.config import get_settings
from app.services.agent.state import CommunityToolResult
from app.services.embeddings import embed_text
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.sparse_vectors import build_query_sparse_vector
from app.services.retrieval_utils import rerank_hybrid, diversify_results

settings = get_settings()
logger = logging.getLogger(__name__)


async def community_tool(
    query: str,
    user_id: str | None = None,
    top_k: int = 12,
    score_threshold: float | None = None,
) -> CommunityToolResult:
    max_summaries = settings.agent_max_community_summaries

    # Le domande "summary" sono per definizione olistiche ("di cosa parla tutto il KB?"):
    # i riassunti di livello "root" (massima aggregazione, vedi community_detection.py)
    # coprono l'intero grafo senza dipendere da quali chunk il retrieval vettoriale trova
    # per primi. Niente ricerca vettoriale necessaria in questo caso, più rapido e completo.
    root_summaries = _fetch_root_community_summaries()
    if root_summaries:
        return _build_result(root_summaries[:max_summaries])

    # Fallback (nessuna community detection ancora eseguita): risali dai chunk più simili
    # alla query alle entità menzionate, poi alle community leaf a cui appartengono.
    query_vector = await embed_text(query)
    threshold = settings.retrieval_score_threshold if score_threshold is None else score_threshold
    search_k = max(top_k, top_k * max(1, settings.retrieval_oversampling_factor))
    query_filter = vector_store.build_user_filter(user_id)

    if settings.qdrant_enable_native_sparse:
        results = vector_store.search_hybrid(
            query_vector,
            build_query_sparse_vector(query),
            top_k=search_k,
            filter=query_filter,
        )
    else:
        results = vector_store.search(
            query_vector,
            top_k=search_k,
            filter=query_filter,
        )

    reranked = rerank_hybrid(query, [r for r in results if r["score"] >= threshold])
    filtered = diversify_results(reranked)[:top_k]

    chunk_ids = [r["payload"].get("chunk_id") for r in filtered if r["payload"].get("chunk_id")]
    entity_ids = _extract_entity_ids_from_chunks(chunk_ids)
    summaries_data = _fetch_community_summaries(entity_ids)
    return _build_result(summaries_data[:max_summaries])


def _build_result(selected: List[dict]) -> CommunityToolResult:
    context = ""
    if selected:
        context = "\n\nPrincipali argomenti trattati nel documento:\n" + "\n\n".join(
            f"Argomento {i + 1} ({s['entity_count']} entità, {s['relation_count']} relazioni collegate):\n{s['summary']}"
            for i, s in enumerate(selected)
        )

    return CommunityToolResult(
        summaries=[s["summary"] for s in selected],
        community_ids=[s["community_id"] for s in selected],
        context=context,
    )


def _extract_entity_ids_from_chunks(chunk_ids: List[str]) -> Set[str]:
    if not chunk_ids:
        return set()
    try:
        with graph_store.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)
                WHERE c.id IN $chunk_ids
                RETURN DISTINCT e.id AS entity_id
                """,
                chunk_ids=chunk_ids,
            )
            return {record["entity_id"] for record in result if record.get("entity_id")}
    except Exception as exc:
        logger.warning("[community_tool] Errore estrazione entità dai chunk: %s", exc)
        return set()


def _fetch_root_community_summaries() -> List[dict]:
    try:
        with graph_store.driver.session() as session:
            result = session.run(
                """
                MATCH (cs:CommunitySummary {level: 'root'})
                RETURN cs.id AS community_id,
                       cs.summary AS summary,
                       cs.entity_count AS entity_count,
                       cs.relation_count AS relation_count,
                       cs.updated_at AS updated_at
                ORDER BY cs.entity_count DESC
                """
            )
            summaries = [
                {
                    "community_id": record["community_id"],
                    "summary": record["summary"],
                    "entity_count": record["entity_count"],
                    "relation_count": record["relation_count"],
                    "updated_at": record["updated_at"],
                }
                for record in result
            ]
            logger.debug("[community_tool] Community summaries di livello root trovate: %s", len(summaries))
            return summaries
    except Exception as exc:
        logger.warning("[community_tool] Errore recupero community summaries root: %s", exc)
        return []


def _fetch_community_summaries(entity_ids: Set[str]) -> List[dict]:
    if not entity_ids:
        return []
    try:
        with graph_store.driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity)-[:BELONGS_TO_COMMUNITY]->(cs:CommunitySummary)
                WHERE e.id IN $entity_ids
                RETURN cs.id AS community_id,
                       cs.summary AS summary,
                       cs.entity_count AS entity_count,
                       cs.relation_count AS relation_count,
                       cs.updated_at AS updated_at
                ORDER BY cs.entity_count DESC
                LIMIT 20
                """,
                entity_ids=list(entity_ids),
            )
            summaries = []
            seen = set()
            for record in result:
                cid = record["community_id"]
                if cid in seen:
                    continue
                seen.add(cid)
                summaries.append({
                    "community_id": cid,
                    "summary": record["summary"],
                    "entity_count": record["entity_count"],
                    "relation_count": record["relation_count"],
                    "updated_at": record["updated_at"],
                })
            logger.debug("[community_tool] Community summaries trovate: %s", len(summaries))
            return summaries
    except Exception as exc:
        logger.warning("[community_tool] Errore recupero community summaries: %s", exc)
        return []


async def run_community_tool(state) -> dict:
    result = await community_tool(
        query=state.get("user_query", ""),
        user_id=state.get("user_id"),
    )
    return {
        "community_results": result,
        "context": result.context,
        "citations": [],
    }
