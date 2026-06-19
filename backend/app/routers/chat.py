from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user_or_mcp
from app.models.models import User
from app.models.schemas import ChatRequest
from app.services.rag_engine import chat_completion

router = APIRouter()


def _retrieval_user_id(user: User) -> str | None:
    if user.email in {"mcp@internal", "librechat@matamune.4nk.eu"}:
        return None
    return str(user.id)


def _request_source(user: User) -> str:
    if user.email == "librechat@matamune.4nk.eu":
        return "librechat"
    if user.email == "mcp@internal":
        return "mcp"
    return "admin"


@router.post("/chat/completions")
async def chat_completions(
    request: ChatRequest,
    current_user: User = Depends(get_current_user_or_mcp),
):
    messages = [{"role": m.role, "content": m.content} for m in request.messages]
    source = _request_source(current_user)
    try:
        if request.stream:
            stream_generator = await chat_completion(
                messages,
                stream=True,
                user_id=_retrieval_user_id(current_user),
                source=source,
                caller_id=str(current_user.id),
                caller_email=current_user.email,
            )
            return StreamingResponse(
                stream_generator,
                media_type="text/event-stream",
            )
        return await chat_completion(
            messages,
            stream=False,
            user_id=_retrieval_user_id(current_user),
            source=source,
            caller_id=str(current_user.id),
            caller_email=current_user.email,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
