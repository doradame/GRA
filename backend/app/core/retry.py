"""Retry helper per chiamate di rete transitorie (LLM, embeddings, Qdrant).

Backoff esponenziale con jitter per evitare il thundering herd sui rate-limit. Nessuna
dipendenza esterna (tenacity non e in requirements): due piccole funzioni, una async per
le coroutine (OpenAI) e una sync per le chiamate bloccanti (Qdrant upsert). Solo le
eccezioni elencate in `retry_on` vengono ritentate (o, se `should_retry` e fornito, solo
quelle per cui ritorna True); gli errori logici (BadRequest, 4xx client, ecc.) propagano.
"""
import asyncio
import logging
import random
import time
from typing import Awaitable, Callable, Tuple, Type

from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def openai_transient() -> Tuple[Type[BaseException], ...]:
    """Eccezioni OpenAI transitorie (rate limit, rete, timeout, 5xx)."""
    from openai import (
        APIConnectionError,
        APITimeoutError,
        InternalServerError,
        RateLimitError,
    )

    return (RateLimitError, APIConnectionError, APITimeoutError, InternalServerError)


async def retry_async(
    coro_factory: Callable[[], Awaitable],
    *,
    retries: int | None = None,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Tuple[Type[BaseException], ...] = (),
    should_retry: Callable[[BaseException], bool] | None = None,
    what: str = "call",
) -> object:
    """Esegue `coro_factory()` ritentando sulle eccezioni transitorie.

    `coro_factory` e una callable zero-arg che restituisce una coroutine NUOVA ad ogni
    tentativo (non passare una coroutine gia creata: non e riawailable). `retries`
    defaulta a settings.api_request_max_retries. Se `should_retry` e fornito e ritorna
    False sull'eccezione catturata, questa propaga subito (es. 4xx client di Qdrant).
    """
    if retries is None:
        retries = settings.api_request_max_retries
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return await coro_factory()
        except retry_on as exc:
            if should_retry is not None and not should_retry(exc):
                raise
            last_exc = exc
            if attempt >= retries:
                break
            delay = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, 0.5)
            logger.warning(
                "[retry] %s failed (attempt %s/%s): %s — retrying in %.1fs",
                what,
                attempt + 1,
                retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def retry_sync(
    func: Callable[[], object],
    *,
    retries: int | None = None,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Tuple[Type[BaseException], ...] = (),
    should_retry: Callable[[BaseException], bool] | None = None,
    what: str = "call",
) -> object:
    """Versione sync di retry_async per chiamate bloccanti (es. Qdrant upsert)."""
    if retries is None:
        retries = settings.api_request_max_retries
    last_exc: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return func()
        except retry_on as exc:
            if should_retry is not None and not should_retry(exc):
                raise
            last_exc = exc
            if attempt >= retries:
                break
            delay = min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, 0.5)
            logger.warning(
                "[retry] %s failed (attempt %s/%s): %s — retrying in %.1fs",
                what,
                attempt + 1,
                retries + 1,
                exc,
                delay,
            )
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc
