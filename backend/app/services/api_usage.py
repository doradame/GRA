import logging
import redis
from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

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


def get_api_usage() -> dict:
    """Return current API usage counters from Redis."""
    try:
        r = _get_redis()
        return {
            "embeddings_calls": int(r.get("api_usage:embeddings_calls") or 0),
            "extraction_calls": int(r.get("api_usage:extraction_calls") or 0),
            "embeddings_tokens": int(r.get("api_usage:embeddings_tokens") or 0),
            "extraction_tokens": int(r.get("api_usage:extraction_tokens") or 0),
        }
    except Exception as e:
        logger.warning("[api_usage] Failed to read usage: %s", e)
        return {
            "embeddings_calls": 0,
            "extraction_calls": 0,
            "embeddings_tokens": 0,
            "extraction_tokens": 0,
        }


def reset_api_usage() -> None:
    """Reset API usage counters. Used when resetting the knowledge base."""
    try:
        r = _get_redis()
        r.delete(
            "api_usage:embeddings_calls",
            "api_usage:extraction_calls",
            "api_usage:embeddings_tokens",
            "api_usage:extraction_tokens",
        )
        logger.info("[api_usage] Usage counters reset")
    except Exception as e:
        logger.warning("[api_usage] Failed to reset usage: %s", e)
