import logging
from typing import List

from app.core.config import get_settings
from app.services.agent.state import VectorToolResult, Citation
from app.services.embeddings import embed_text
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.sparse_vectors import build_query_sparse_vector
from app.services.reranker import rerank_cross_encoder
from app.services.retrieval_utils import (
    format_reference,
    extract_quote,
    rerank_hybrid,
    diversify_results,
)

settings = get_settings()
logger = logging.getLogger(__name__)


async def vector_tool(
    query: str,
    user_id: str | None = None,
    top_k: int = 12,
    score_threshold: float | None = None,
) -> VectorToolResult:
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

    # Vedi rag_engine.build_context: il cross-encoder valuta tutto il pool oversampled,
    # la soglia su score di fusione RRF si applica solo al fallback lessicale.
    reranked = rerank_cross_encoder(query, results)
    if reranked is None:
        candidates = [r for r in results if r["score"] >= threshold]
        reranked = rerank_hybrid(query, candidates)
    filtered = diversify_results(reranked)[:top_k]

    citations: List[Citation] = []
    context_parts = []
    chunk_ids = []
    for r in filtered:
        payload = r["payload"]
        chunk_index = payload.get("index")
        reference = format_reference(payload)
        quote = extract_quote(payload.get("text", ""))
        citations.append(
            Citation(
                chunk_id=payload.get("chunk_id", ""),
                document_id=payload.get("document_id", ""),
                filename=payload.get("filename", ""),
                text=payload.get("text", ""),
                score=r["score"],
                chunk_index=chunk_index if isinstance(chunk_index, int) else None,
                section_title=payload.get("section_title") or None,
                char_start=payload.get("char_start"),
                char_end=payload.get("char_end"),
                page_start=payload.get("page_start"),
                page_end=payload.get("page_end"),
                document_page_count=payload.get("document_page_count"),
                quote=quote,
                reference=reference,
            )
        )
        context_parts.append(
            f"---\nFonte: {reference}\nEstratto: \"{quote}\"\nTesto completo:\n{payload.get('text')}"
        )
        chunk_id = payload.get("chunk_id")
        if chunk_id:
            chunk_ids.append(chunk_id)

    local_facts = []
    if chunk_ids:
        local_facts = _fetch_local_graph_facts(chunk_ids)

    graph_context = ""
    if local_facts:
        graph_context = "\n\nFatti correlati estratti dal grafo delle entità:\n" + "\n".join(
            f"- {fact}" for fact in local_facts
        )

    context = "\n".join(context_parts) + graph_context
    return VectorToolResult(
        chunks=[r["payload"] for r in filtered],
        local_graph_facts=local_facts,
        context=context,
        citations=citations,
    )


def _fetch_local_graph_facts(chunk_ids: List[str]) -> List[str]:
    if not chunk_ids:
        return []
    max_facts = settings.agent_max_graph_facts
    try:
        with graph_store.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)-[r]-(e2:Entity)
                WHERE c.id IN $chunk_ids
                RETURN e.name AS source, type(r) AS rel_type, e2.name AS target
                LIMIT 200
                """,
                chunk_ids=chunk_ids,
            )
            seen = set()
            facts = []
            for record in result:
                source = graph_store._stringify_name(record.get("source"))
                target = graph_store._stringify_name(record.get("target"))
                rel_type = record.get("rel_type", "RELATED_TO")
                key = (source.lower(), rel_type.lower(), target.lower())
                if key in seen:
                    continue
                seen.add(key)
                facts.append(f"{source} --[{rel_type}]--> {target}")
                if len(facts) >= max_facts:
                    break
            logger.debug("[vector_tool] Local graph facts: %s", len(facts))
            return facts
    except Exception as exc:
        logger.warning("[vector_tool] Errore recupero sottografo locale: %s", exc)
        return []


async def run_vector_tool(state) -> dict:
    result = await vector_tool(
        query=state.get("user_query", ""),
        user_id=state.get("user_id"),
    )
    return {
        "vector_results": result,
        "context": result.context,
        "citations": result.citations,
        "tool_used": "vector",
    }
