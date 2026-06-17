from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user_or_mcp
from app.models.models import User
from app.models.schemas import GraphExploreResponse
from app.services.graph_store import graph_store

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
