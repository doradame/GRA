import json
import time
import uuid
import re
from typing import List, Dict, Any, AsyncGenerator
from openai import AsyncOpenAI
from app.core.config import get_settings
from app.services.embeddings import embed_text
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store
from app.services.sparse_vectors import build_sparse_vector
from app.models.schemas import Citation
from app.services.agent.graph import agent_graph
from app.services.agent.state import AgentState
from app.services.query_log import record_query_log
from app.services.reranker import rerank_cross_encoder
from app.services.retrieval_utils import (
    format_reference,
    extract_quote,
    rerank_hybrid,
    diversify_results,
)

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """Sei un assistente conversazionale che aiuta l'utente usando i documenti caricati nella knowledge base.

Regole:
- Per domande sui documenti, usa SOLO le informazioni presenti nel contesto fornito.
- Se la risposta si trova nei documenti, rispondi in modo completo, chiaro e naturale; non limitarti a una frase secca.
- Quando citi una fonte, usa riferimenti leggibili: file, pagina se disponibile, sezione/parte se disponibile.
- Non citare mai ID tecnici di chunk o UUID nella risposta all'utente.
- Quando utile, includi un breve virgolettato dal contesto.
- Se l'utente fa un saluto o una domanda generale (es. "chi sei?", "ciao"), rispondi normalmente in modo cordiale.
- Se l'utente chiede qualcosa non presente nei documenti, spiega gentilmente che non hai informazioni al riguardo nella knowledge base.
"""


async def build_context(
    query: str,
    top_k: int = 12,
    score_threshold: float | None = None,
    user_id: str | None = None,
) -> tuple[str, List[Citation]]:
    query_vector = await embed_text(query)
    threshold = settings.retrieval_score_threshold if score_threshold is None else score_threshold
    search_k = max(top_k, top_k * max(1, settings.retrieval_oversampling_factor))
    query_filter = vector_store.build_user_filter(user_id)
    if settings.qdrant_enable_native_sparse:
        results = vector_store.search_hybrid(
            query_vector,
            build_sparse_vector(query),
            top_k=search_k,
            filter=query_filter,
        )
    else:
        results = vector_store.search(
            query_vector,
            top_k=search_k,
            filter=query_filter,
        )

    # Keep only results with a meaningful similarity score
    candidates = [r for r in results if r["score"] >= threshold]
    reranked = rerank_cross_encoder(query, candidates)
    if reranked is None:
        reranked = rerank_hybrid(query, candidates)
    filtered = diversify_results(reranked)[:top_k]

    citations: List[Citation] = []
    context_parts = []
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

    # Optional graph expansion: pick top entity names from retrieved chunks and expand
    entity_names = await _extract_top_entities(query)
    graph_context = ""
    for name in entity_names[:3]:
        data = graph_store.explore_entity(name, depth=1)
        if data["entities"]:
            graph_context += f"\nInformazioni correlate a '{name}':\n"
            for rel in data["relations"][:5]:
                graph_context += f"- {rel['source']} --[{rel['type']}]--> {rel['target']}\n"

    context = "\n".join(context_parts) + "\n" + graph_context
    return context, citations


async def _extract_top_entities(query: str) -> List[str]:
    # Simple heuristic: extract capitalized phrases or quoted terms
    entities = re.findall(r'\"(.+?)\"', query)
    # add capitalized sequences
    entities += re.findall(r'[A-Z][a-zA-Z\s]+', query)
    return list(set([e.strip() for e in entities if len(e.strip()) > 2]))


async def chat_completion(
    messages: List[Dict[str, str]],
    stream: bool = False,
    user_id: str | None = None,
    source: str = "api",
    caller_id: str | None = None,
    caller_email: str | None = None,
) -> Dict[str, Any]:
    if not messages:
        raise ValueError("messages cannot be empty")

    user_query = messages[-1]["content"]

    initial_state: AgentState = {
        "messages": messages,
        "user_query": user_query,
        "user_id": user_id,
        "intent": "factual",
        "reasoning": "",
        "vector_results": None,
        "cypher_results": None,
        "community_results": None,
        "context": "",
        "citations": [],
        "answer": None,
        "error": None,
    }

    start = time.monotonic()
    try:
        result = await agent_graph.ainvoke(initial_state)
    except Exception as exc:
        await record_query_log(
            source=source,
            user_id=caller_id,
            user_email=caller_email,
            query=user_query,
            error=str(exc),
            latency_ms=int((time.monotonic() - start) * 1000),
        )
        raise

    content = result.get("answer") or ""
    citations = result.get("citations", [])

    await record_query_log(
        source=source,
        user_id=caller_id,
        user_email=caller_email,
        query=user_query,
        intent=result.get("intent"),
        reasoning=result.get("reasoning"),
        answer=content,
        citation_count=len(citations),
        error=result.get("error"),
        latency_ms=int((time.monotonic() - start) * 1000),
    )

    if stream:
        if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
            return _stream_static_response(content, citations)
        system_content = SYSTEM_PROMPT
        if result.get("context"):
            system_content += "\n\nCONTESTO:\n" + str(result["context"])
        augmented_messages = [{"role": "system", "content": system_content}] + messages
        return _stream_response(augmented_messages, citations)

    return {
        "id": str(uuid.uuid4()),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": settings.openai_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "citations": [c.model_dump() for c in citations],
    }


async def _stream_response(messages: List[Dict[str, str]], citations: List[Citation]) -> AsyncGenerator[str, None]:
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=messages,
        temperature=settings.llm_temperature,
        stream=True,
    )
    completion_id = str(uuid.uuid4())
    created = int(time.time())

    initial_payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": settings.openai_model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}}],
    }
    yield f"data: {json.dumps(initial_payload)}\n\n"

    async for chunk in response:
        delta = chunk.choices[0].delta.content or ""
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": settings.openai_model,
            "choices": [{"index": 0, "delta": {"content": delta}}],
        }
        yield f"data: {json.dumps(payload)}\n\n"

    # Append citations as final chunk metadata
    citations_payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": settings.openai_model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "citations": [c.model_dump() for c in citations],
    }
    yield f"data: {json.dumps(citations_payload)}\n\n"
    yield "data: [DONE]\n\n"


async def _stream_static_response(content: str, citations: List[Citation]) -> AsyncGenerator[str, None]:
    completion_id = str(uuid.uuid4())
    created = int(time.time())

    initial_payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": settings.openai_model,
        "choices": [{"index": 0, "delta": {"role": "assistant"}}],
    }
    yield f"data: {json.dumps(initial_payload)}\n\n"

    content_payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": settings.openai_model,
        "choices": [{"index": 0, "delta": {"content": content}}],
    }
    yield f"data: {json.dumps(content_payload)}\n\n"

    citations_payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": settings.openai_model,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "citations": [c.model_dump() for c in citations],
    }
    yield f"data: {json.dumps(citations_payload)}\n\n"
    yield "data: [DONE]\n\n"
