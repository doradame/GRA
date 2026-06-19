import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.core.auth import get_current_active_admin
from app.core.database import get_db
from app.models.models import User, Document, IngestionJob, QueryLog, ServiceHealthCheck
from app.models.schemas import (
    AdminMetricsOut,
    IngestionJobList,
    QueryLogList,
    ServiceHealthOut,
)
from app.services.health import check_all_services
from app.services.api_usage import get_api_usage

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/metrics", response_model=AdminMetricsOut)
async def get_admin_metrics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    status_counts = {}
    for status in [
        "uploaded",
        "parsing",
        "chunking",
        "embedding",
        "vector_indexing",
        "graph_indexing",
        "completed",
        "error",
    ]:
        result = await db.execute(select(func.count(Document.id)).where(Document.status == status))
        status_counts[status] = result.scalar() or 0

    ingestions_result = await db.execute(
        select(IngestionJob).order_by(desc(IngestionJob.created_at)).limit(20)
    )
    ingestions = ingestions_result.scalars().all()

    queries_result = await db.execute(
        select(QueryLog).order_by(desc(QueryLog.created_at)).limit(20)
    )
    queries = queries_result.scalars().all()

    services_result = await db.execute(select(ServiceHealthCheck))
    services = services_result.scalars().all()

    api_usage = get_api_usage()

    return AdminMetricsOut(
        documents=status_counts,
        recent_ingestions=list(ingestions),
        recent_queries=list(queries),
        services=services,
        api_usage=api_usage,
    )


@router.get("/metrics/ingestion", response_model=IngestionJobList)
async def list_ingestion_metrics(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    safe_limit = min(max(limit, 1), 200)
    result = await db.execute(
        select(IngestionJob).order_by(desc(IngestionJob.created_at)).offset(offset).limit(safe_limit)
    )
    items = result.scalars().all()
    total_result = await db.execute(select(func.count(IngestionJob.id)))
    total = total_result.scalar() or 0
    return IngestionJobList(items=list(items), total=total)


@router.get("/metrics/queries", response_model=QueryLogList)
async def list_query_metrics(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    safe_limit = min(max(limit, 1), 200)
    result = await db.execute(
        select(QueryLog).order_by(desc(QueryLog.created_at)).offset(offset).limit(safe_limit)
    )
    items = result.scalars().all()
    total_result = await db.execute(select(func.count(QueryLog.id)))
    total = total_result.scalar() or 0
    return QueryLogList(items=list(items), total=total)


@router.get("/health", response_model=list[ServiceHealthOut])
async def get_health_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    result = await db.execute(select(ServiceHealthCheck))
    services = result.scalars().all()
    if not services or all((datetime.utcnow() - s.last_check_at).total_seconds() > 60 for s in services):
        return await _refresh_health(db)
    return services


@router.post("/health/check", response_model=list[ServiceHealthOut])
async def force_health_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    return await _refresh_health(db)


async def _refresh_health(db: AsyncSession) -> list[ServiceHealthCheck]:
    results = await check_all_services()
    now = datetime.utcnow()
    updated = []
    for service, data in results.items():
        result = await db.execute(select(ServiceHealthCheck).where(ServiceHealthCheck.service == service))
        row = result.scalar_one_or_none()
        if row is None:
            row = ServiceHealthCheck(service=service)
            db.add(row)
        row.status = data["status"]
        row.latency_ms = data.get("latency_ms")
        row.last_check_at = now
        row.error_message = data.get("error_message")
        updated.append(row)
    await db.commit()
    for row in updated:
        await db.refresh(row)
    return updated
