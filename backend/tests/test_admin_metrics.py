import pytest
from httpx import AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_admin_metrics_requires_auth():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/metrics")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_health_requires_auth():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/health")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_metrics_ingestion_requires_auth():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/metrics/ingestion")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_metrics_queries_requires_auth():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/v1/admin/metrics/queries")
    assert response.status_code == 401
