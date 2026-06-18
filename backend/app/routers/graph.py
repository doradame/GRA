from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user_or_mcp, get_current_active_admin
from app.models.models import User
from app.models.schemas import GraphExploreResponse
from app.services.graph_store import graph_store
from app.tasks.entity_resolution import resolve_entities_task

router = APIRouter()


@router.get("/explore", response_model=GraphExploreResponse)
async def explore_graph(
    entity: str,
    depth: int = 1,
    current_user: User = Depends(get_current_user_or_mcp),
):
    if not entity:
        raise HTTPException(status_code=400, detail="entity query required")
    data = graph_store.explore_entity(entity, depth=depth)
    return GraphExploreResponse(**data)


@router.post("/resolve-entities")
async def trigger_entity_resolution(
    threshold: float = 0.93,
    current_user: User = Depends(get_current_active_admin),
):
    """Avvia il task di entity resolution fuzzy sul grafo.

    Richiede privilegi di amministratore. Il task viene eseguito in background
    dal worker Celery.
    """
    task = resolve_entities_task.delay(threshold=threshold)
    return {"task_id": task.id, "status": "queued", "threshold": threshold}
