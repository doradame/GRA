import time
import logging
from typing import Awaitable

import httpx
import redis
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import engine
from app.services.storage import storage
from app.services.vector_store import vector_store
from app.services.graph_store import graph_store

logger = logging.getLogger(__name__)

DEGRADED_LATENCY_MS = 1000
TIMEOUT_SECONDS = 5


async def _check_postgres() -> dict:
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Postgres check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_neo4j() -> dict:
    start = time.perf_counter()
    try:
        graph_store.check_connection()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Neo4j check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_qdrant() -> dict:
    start = time.perf_counter()
    try:
        vector_store.health()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Qdrant check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_minio() -> dict:
    start = time.perf_counter()
    try:
        storage.client.list_buckets()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] MinIO check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_redis() -> dict:
    start = time.perf_counter()
    try:
        local_settings = get_settings()
        r = redis.from_url(local_settings.celery_broker_url, socket_connect_timeout=TIMEOUT_SECONDS)
        r.ping()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] Redis check failed")
        return {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}


async def _check_openai() -> dict:
    local_settings = get_settings()
    if not local_settings.openai_api_key:
        return {"status": "error", "latency_ms": None, "error_message": "OPENAI_API_KEY not set"}
    if local_settings.openai_api_key == "sk-test":
        return {"status": "degraded", "latency_ms": None, "error_message": "Demo mode (sk-test)"}

    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {local_settings.openai_api_key}"},
            )
            response.raise_for_status()
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "ok", "latency_ms": latency}
    except Exception as e:
        logger.exception("[health] OpenAI check failed")
        return {"status": "degraded", "latency_ms": None, "error_message": str(e)[:500]}


async def check_all_services() -> dict[str, dict]:
    """Run all health checks concurrently and return a map service -> result."""
    checks = {
        "postgres": _check_postgres(),
        "neo4j": _check_neo4j(),
        "qdrant": _check_qdrant(),
        "minio": _check_minio(),
        "redis": _check_redis(),
        "openai": _check_openai(),
    }
    results = {}
    for name, coro in checks.items():
        try:
            result = await coro
        except Exception as e:
            logger.exception("[health] Unexpected error checking %s", name)
            result = {"status": "error", "latency_ms": None, "error_message": str(e)[:500]}
        if (result.get("latency_ms") or 0) > DEGRADED_LATENCY_MS and result["status"] == "ok":
            result["status"] = "degraded"
        results[name] = result
    return results
