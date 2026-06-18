from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user_or_mcp, get_current_active_admin
from app.models.models import User
from app.models.schemas import GraphExploreResponse, CommunitySummaryList, CommunitySummaryOut
from app.services.graph_store import graph_store
from app.tasks.entity_resolution import resolve_entities_task
from app.tasks.community_detection import community_detection_task

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


@router.post("/community-detection")
async def trigger_community_detection(
    algorithm: str = "louvain",
    resolution: float = 1.0,
    current_user: User = Depends(get_current_active_admin),
):
    """Avvia il task di community detection sul grafo.

    Richiede privilegi di amministratore. Il task viene eseguito in background
    dal worker Celery.
    """
    task = community_detection_task.delay(algorithm=algorithm, resolution=resolution)
    return {"task_id": task.id, "status": "queued", "algorithm": algorithm, "resolution": resolution}


@router.get("/community-summaries", response_model=CommunitySummaryList)
async def list_community_summaries(
    current_user: User = Depends(get_current_user_or_mcp),
):
    """Restituisce l'elenco dei riassunti delle community salvati nel grafo."""
    with graph_store.driver.session() as session:
        result = session.run(
            """
            MATCH (cs:CommunitySummary)
            RETURN cs.id AS community_id,
                   cs.summary AS summary,
                   cs.entity_count AS entity_count,
                   cs.relation_count AS relation_count,
                   cs.updated_at AS updated_at
            ORDER BY cs.updated_at DESC
            """
        )
        items = []
        for record in result:
            items.append(CommunitySummaryOut(**record.data()))
    return CommunitySummaryList(items=items, total=len(items))
