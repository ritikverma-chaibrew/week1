import time

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings
from app.models.conversation import ApiKeyIn, MessageIn, StartPractice
from app.routes.deps import (
    BYOK_TTL_SECONDS,
    current_user,
    get_config,
    get_db,
    get_provider_factory,
)
from app.services import conversation as service
from app.services.ai.base import AIConfigError

router = APIRouter(prefix="/api")


@router.post("/conversations", status_code=201)
@router.post("/practice/start", status_code=201)
async def start_conversation(
    body: StartPractice | None = None,
    db=Depends(get_db),
    user_id: str = Depends(current_user),
    provider_factory=Depends(get_provider_factory),
    settings: Settings = Depends(get_config),
):
    return await service.start_conversation(
        db, provider_factory, user_id, body or StartPractice(), settings.max_context_messages
    )


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str, db=Depends(get_db), user_id: str = Depends(current_user)
):
    try:
        return await service.get_conversation(db, user_id, conversation_id)
    except service.ConversationNotFound:
        raise HTTPException(404, "Conversation not found.")


@router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: MessageIn,
    db=Depends(get_db),
    user_id: str = Depends(current_user),
    provider_factory=Depends(get_provider_factory),
    settings: Settings = Depends(get_config),
):
    try:
        return await service.send_message(
            db,
            provider_factory(),
            user_id,
            conversation_id,
            body.content,
            settings.max_context_messages,
        )
    except service.ConversationNotFound:
        raise HTTPException(404, "Conversation not found.")


@router.put("/session/key", status_code=204)
async def set_session_key(
    body: ApiKeyIn,
    request: Request,
    user_id: str = Depends(current_user),
    settings: Settings = Depends(get_config),
):
    """Optional bring-your-own-key. Held in server memory only; never stored or echoed."""
    if not (settings.gemma_api_url or "").strip():
        raise AIConfigError("GEMMA_API_URL must be configured on the server to use your own key.")
    request.app.state.byok[user_id] = (body.api_key.strip(), time.monotonic() + BYOK_TTL_SECONDS)


@router.delete("/session/key", status_code=204)
async def clear_session_key(request: Request, user_id: str = Depends(current_user)):
    request.app.state.byok.pop(user_id, None)
