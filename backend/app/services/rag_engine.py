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

settings = get_settings()
client = AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """Sei un assistente conversazionale che aiuta l'utente usando i documenti caricati nella knowledge base.

Regole:
- Per domande sui documenti, usa SOLO le informazioni presenti nel contesto fornito.
- Se la risposta si trova nei documenti, rispondi in modo completo, chiaro e naturale; non limitarti a una frase secca.
- Cita i file rilevanti quando è utile, senza esagerare.
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
    reranked = _rerank_hybrid(query, [r for r in results if r["score"] >= threshold])
    filtered = _diversify_results(reranked)[:top_k]

    citations: List[Citation] = []
    context_parts = []
    for r in filtered:
        payload = r["payload"]
        citations.append(
            Citation(
                chunk_id=payload.get("chunk_id", ""),
                document_id=payload.get("document_id", ""),
                filename=payload.get("filename", ""),
                text=payload.get("text", ""),
                score=r["score"],
            )
        )
        context_parts.append(
            f"---\nFile: {payload.get('filename')}\nChunk: {payload.get('chunk_id')}\n{payload.get('text')}"
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
    import re
    entities = re.findall(r'\"(.+?)\"', query)
    # add capitalized sequences
    entities += re.findall(r'[A-Z][a-zA-Z\s]+', query)
    return list(set([e.strip() for e in entities if len(e.strip()) > 2]))


def _diversify_results(results: List[dict], max_similarity: float = 0.82) -> List[dict]:
    selected: List[dict] = []
    selected_tokens: List[set[str]] = []

    for result in results:
        text = str(result.get("payload", {}).get("text", ""))
        tokens = _token_set(text)
        if not tokens:
            selected.append(result)
            selected_tokens.append(tokens)
            continue
        if all(_jaccard(tokens, existing) <= max_similarity for existing in selected_tokens):
            selected.append(result)
            selected_tokens.append(tokens)

    return selected


def _rerank_hybrid(query: str, results: List[dict]) -> List[dict]:
    query_tokens = _token_set(query)
    weight = min(max(settings.retrieval_lexical_weight, 0.0), 1.0)
    if not query_tokens or weight == 0:
        return results

    reranked = []
    for result in results:
        text = str(result.get("payload", {}).get("text", ""))
        lexical_score = _jaccard(query_tokens, _token_set(text))
        vector_score = float(result.get("score", 0.0))
        combined = (vector_score * (1 - weight)) + (lexical_score * weight)
        enriched = dict(result)
        enriched["hybrid_score"] = combined
        enriched["lexical_score"] = lexical_score
        reranked.append(enriched)
    return sorted(reranked, key=lambda item: item["hybrid_score"], reverse=True)


def _token_set(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[\wÀ-ÿ]{3,}", text.casefold())
        if token not in {"the", "and", "for", "con", "per", "che", "del", "della", "gli", "una"}
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


async def chat_completion(
    messages: List[Dict[str, str]],
    stream: bool = False,
    user_id: str | None = None,
) -> Dict[str, Any]:
    if not messages:
        raise ValueError("messages cannot be empty")

    user_query = messages[-1]["content"]
    context, citations = await build_context(user_query, user_id=user_id)

    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        content = (
            "[MODALITÀ TEST] Ho trovato i seguenti chunk rilevanti nel contesto documentale. "
            "Configura una chiave OpenAI valida per ricevere risposte generate dal modello."
        )
    else:
        if context.strip():
            system_content = SYSTEM_PROMPT + "\n\nCONTESTO:\n" + context
        else:
            system_content = SYSTEM_PROMPT + "\n\nNon sono stati trovati documenti rilevanti per questa domanda."

        augmented_messages = [
            {"role": "system", "content": system_content},
        ] + messages

        if stream:
            return _stream_response(augmented_messages, citations)

        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=augmented_messages,
            temperature=settings.llm_temperature,
        )
        content = response.choices[0].message.content

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
