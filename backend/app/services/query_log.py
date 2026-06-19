import logging

from app.core.database import AsyncSessionLocal
from app.models.models import QueryLog

logger = logging.getLogger(__name__)


async def record_query_log(
    *,
    source: str,
    query: str,
    user_id: str | None = None,
    user_email: str | None = None,
    intent: str | None = None,
    reasoning: str | None = None,
    answer: str | None = None,
    citation_count: int = 0,
    error: str | None = None,
    latency_ms: int | None = None,
    tool_used: str | None = None,
    iteration_count: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_estimate_usd: float | None = None,
) -> None:
    """Best-effort persistence of a chat query for the admin log viewer. Never raises."""
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                QueryLog(
                    source=source,
                    user_id=user_id,
                    user_email=user_email,
                    query=query,
                    intent=intent,
                    reasoning=reasoning,
                    answer=answer,
                    citation_count=citation_count,
                    error=error,
                    latency_ms=latency_ms,
                    tool_used=tool_used,
                    iteration_count=iteration_count,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_estimate_usd=cost_estimate_usd,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("[query_log] Failed to persist query log entry")
