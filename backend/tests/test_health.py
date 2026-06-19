import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.services.health import check_all_services


@pytest.mark.asyncio
async def test_check_all_services_maps_names():
    with patch("app.services.health.engine") as mock_engine, \
         patch("app.services.health.graph_store") as mock_graph, \
         patch("app.services.health.vector_store") as mock_vector, \
         patch("app.services.health.storage") as mock_storage, \
         patch("app.services.health.redis") as mock_redis, \
         patch("app.services.health.httpx") as mock_httpx, \
         patch("app.services.health.get_settings") as mock_settings:

        mock_settings.return_value.openai_api_key = "sk-test"
        mock_settings.return_value.celery_broker_url = "redis://localhost:6379/0"

        mock_conn = MagicMock()
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)

        results = await check_all_services()

        assert set(results.keys()) == {"postgres", "neo4j", "qdrant", "minio", "redis", "openai"}
        assert results["openai"]["status"] == "degraded"
