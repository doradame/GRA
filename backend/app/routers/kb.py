from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.auth import get_current_user, get_current_user_or_mcp
from app.models.models import User, Document, Chunk
from app.services.graph_store import graph_store
from app.services.vector_store import vector_store
from app.services.api_usage import get_api_usage
from app.services.rag_engine import build_context

router = APIRouter()


def _retrieval_user_id(user: User) -> str | None:
    if user.email in {"mcp@internal", "librechat@matamune.4nk.eu"}:
        return None
    return str(user.id)


@router.get("/info")
async def knowledge_base_info(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = str(current_user.id)
    doc_count_result = await db.execute(
        select(func.count(Document.id)).where(Document.created_by == current_user.id)
    )
    doc_count = doc_count_result.scalar()

    chunk_count_result = await db.execute(
        select(func.count(Chunk.id))
        .join(Document, Chunk.document_id == Document.id)
        .where(Document.created_by == current_user.id)
    )
    chunk_count = chunk_count_result.scalar()

    graph_stats = graph_store.get_stats(user_id=user_id)

    vector_count = vector_store.count(user_id=user_id)

    return {
        "documents": doc_count,
        "chunks": chunk_count,
        "entities": graph_stats["entities"],
        "relations": graph_stats["relations"],
        "vectors": vector_count,
    }


@router.get("/usage")
async def knowledge_base_api_usage(
    current_user: User = Depends(get_current_user),
):
    """Return OpenAI API usage counters tracked during ingestion."""
    return get_api_usage()


@router.get("/search")
async def search_knowledge_base(
    query: str = Query(..., min_length=1),
    top_k: int = Query(default=8, ge=1, le=24),
    current_user: User = Depends(get_current_user_or_mcp),
):
    """Return retrieved knowledge-base chunks without generating a final answer."""
    _, citations = await build_context(
        query,
        top_k=top_k,
        user_id=_retrieval_user_id(current_user),
    )
    return {
        "query": query,
        "top_k": top_k,
        "results": [citation.model_dump() for citation in citations],
    }
