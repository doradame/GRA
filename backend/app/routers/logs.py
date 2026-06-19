from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_active_admin
from app.models.models import User, QueryLog
from app.models.schemas import QueryLogList

router = APIRouter()


@router.get("/queries", response_model=QueryLogList)
async def list_query_logs(
    source: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    q: str | None = Query(default=None, description="Search inside the query text"),
    errors_only: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """List logged chat queries (LibreChat, MCP, admin) for debugging and auditing. Admin only."""
    filters = []
    if source:
        filters.append(QueryLog.source == source)
    if intent:
        filters.append(QueryLog.intent == intent)
    if q:
        filters.append(QueryLog.query.ilike(f"%{q}%"))
    if errors_only:
        filters.append(QueryLog.error.isnot(None))

    stmt = select(QueryLog).where(*filters).order_by(desc(QueryLog.created_at)).offset(skip).limit(limit)
    result = await db.execute(stmt)
    items = result.scalars().all()

    count_stmt = select(func.count(QueryLog.id)).where(*filters)
    total = (await db.execute(count_stmt)).scalar() or 0

    return QueryLogList(items=items, total=total)
