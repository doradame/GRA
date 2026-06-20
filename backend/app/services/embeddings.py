from typing import List
import hashlib
import math
from openai import AsyncOpenAI, BadRequestError
from app.core.config import get_settings
from app.core.retry import openai_transient, retry_async
from app.services.api_usage import increment_embeddings_calls

settings = get_settings()
VECTOR_SIZE = settings.embedding_dimensions


def _fallback_embedding(text: str) -> List[float]:
    """Generates a deterministic pseudo-embedding for testing without a real API key."""
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    vec = []
    for i in range(VECTOR_SIZE):
        byte = seed[i % len(seed)]
        # normalizza tra -1 e 1
        val = (byte / 255.0) * 2 - 1
        vec.append(val)
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


async def embed_texts(texts: List[str]) -> List[List[float]]:
    if not texts:
        return []
    if not settings.openai_api_key or settings.openai_api_key.startswith("sk-test"):
        return [_fallback_embedding(t) for t in texts]

    # Create a fresh client bound to the current event loop.
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    try:
        embeddings: List[List[float]] = []
        batch_size = max(1, settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            embeddings.extend(await _embed_batch(client, batch))
        return embeddings
    finally:
        await client.close()


async def embed_text(text: str) -> List[float]:
    embeddings = await embed_texts([text])
    return embeddings[0]


async def _embed_batch(client: AsyncOpenAI, texts: List[str]) -> List[List[float]]:
    kwargs = {
        "model": settings.embedding_model,
        "input": texts,
    }
    if settings.embedding_dimensions:
        kwargs["dimensions"] = settings.embedding_dimensions

    try:
        response = await retry_async(
            lambda: client.embeddings.create(**kwargs),
            retry_on=openai_transient(),
            what="embeddings",
        )
    except BadRequestError:
        # Il modello/payload non supporta `dimensions`: retry senza (errore logico, non transitorio).
        kwargs.pop("dimensions", None)
        response = await retry_async(
            lambda: client.embeddings.create(**kwargs),
            retry_on=openai_transient(),
            what="embeddings",
        )

    tokens = 0
    if response.usage:
        tokens = response.usage.total_tokens or 0
    increment_embeddings_calls(tokens=tokens)
    return [item.embedding for item in response.data]
