import logging
import redis
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Approximate cost per 1M tokens (input / output) in USD.
# Override via env in future if needed.
MODEL_COSTS: dict[str, dict[str, float]] = {
    "gpt-5.4": {"input": 2.50, "output": 10.00},
    "gpt-5.4-mini": {"input": 0.15, "output": 0.60},
    "gpt-5.4-nano": {"input": 0.075, "output": 0.30},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


# Redis connection shared across the app. Redis is already used by Celery.
_redis_client = None


def _get_redis() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(settings.celery_broker_url, decode_responses=True)
    return _redis_client


def increment_embeddings_calls(tokens: int = 0) -> None:
    """Increment the counter for OpenAI embeddings API calls."""
    try:
        r = _get_redis()
        r.incr("api_usage:embeddings_calls")
        if tokens:
            r.incrby("api_usage:embeddings_tokens", tokens)
        logger.debug("[api_usage] Embeddings call counted (tokens=%s)", tokens)
    except Exception as e:
        logger.warning("[api_usage] Failed to track embeddings usage: %s", e)


def increment_extraction_calls(tokens: int = 0) -> None:
    """Increment the counter for OpenAI chat completions API calls (entity/relation extraction)."""
    try:
        r = _get_redis()
        r.incr("api_usage:extraction_calls")
        if tokens:
            r.incrby("api_usage:extraction_tokens", tokens)
        logger.debug("[api_usage] Extraction call counted (tokens=%s)", tokens)
    except Exception as e:
        logger.warning("[api_usage] Failed to track extraction usage: %s", e)


def increment_contextual_retrieval_calls(tokens: int = 0) -> None:
    """Increment the counter for OpenAI chat completions API calls (rich contextual retrieval)."""
    try:
        r = _get_redis()
        r.incr("api_usage:contextual_retrieval_calls")
        if tokens:
            r.incrby("api_usage:contextual_retrieval_tokens", tokens)
        logger.debug("[api_usage] Contextual retrieval call counted (tokens=%s)", tokens)
    except Exception as e:
        logger.warning("[api_usage] Failed to track contextual retrieval usage: %s", e)


def get_api_usage() -> dict:
    """Return current API usage counters from Redis."""
    try:
        r = _get_redis()
        return {
            "embeddings_calls": int(r.get("api_usage:embeddings_calls") or 0),
            "extraction_calls": int(r.get("api_usage:extraction_calls") or 0),
            "contextual_retrieval_calls": int(r.get("api_usage:contextual_retrieval_calls") or 0),
            "embeddings_tokens": int(r.get("api_usage:embeddings_tokens") or 0),
            "extraction_tokens": int(r.get("api_usage:extraction_tokens") or 0),
            "contextual_retrieval_tokens": int(r.get("api_usage:contextual_retrieval_tokens") or 0),
        }
    except Exception as e:
        logger.warning("[api_usage] Failed to read usage: %s", e)
        return {
            "embeddings_calls": 0,
            "extraction_calls": 0,
            "contextual_retrieval_calls": 0,
            "embeddings_tokens": 0,
            "extraction_tokens": 0,
            "contextual_retrieval_tokens": 0,
        }


def reset_api_usage() -> None:
    """Reset API usage counters. Used when resetting the knowledge base."""
    try:
        r = _get_redis()
        r.delete(
            "api_usage:embeddings_calls",
            "api_usage:extraction_calls",
            "api_usage:contextual_retrieval_calls",
            "api_usage:embeddings_tokens",
            "api_usage:extraction_tokens",
            "api_usage:contextual_retrieval_tokens",
        )
        logger.info("[api_usage] Usage counters reset")
    except Exception as e:
        logger.warning("[api_usage] Failed to reset usage: %s", e)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    """Return estimated cost in USD for a given model and token counts."""
    rates = MODEL_COSTS.get(
        model,
        MODEL_COSTS.get("gpt-4o-mini", {"input": 0.15, "output": 0.60}),
    )
    input_cost = (input_tokens / 1_000_000) * rates["input"]
    output_cost = (output_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 6)
