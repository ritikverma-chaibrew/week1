import logging
from typing import Literal
import time

import httpx
from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Settings
from app.models.conversation import MessageIn, ProviderIn, StartPractice
from app.routes.deps import (
    BYOK_TTL_SECONDS,
    _session_ai,
    current_user,
    get_config,
    get_db,
    get_provider_factory,
)
from app.services import conversation as service
from app.services.ai import build_provider

logger = logging.getLogger(__name__)
MASK = "**********"
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


@router.put("/session/provider", status_code=204)
async def set_session_provider(
    body: ProviderIn,
    request: Request,
    user_id: str = Depends(current_user),
    settings: Settings = Depends(get_config),
):
    """Choose LM Studio or Google AI Studio for this learner. Held in server memory only."""
    session = {
        "mode": body.mode,
        "api_key": body.api_key.strip().strip("\"'"),
        "model": body.model.strip(),
    }
    if getattr(request.app.state, "provider", None) is None:  # verify unless a test provider is injected
        await build_provider(settings, session).ping()
    request.app.state.byok[user_id] = (session, time.monotonic() + BYOK_TTL_SECONDS)


@router.get("/session/provider")
async def get_session_provider(
    request: Request,
    user_id: str = Depends(current_user),
    settings: Settings = Depends(get_config),
):
    """What the coach is using right now. The key itself is never returned, only a mask."""
    session = _session_ai(request, user_id)
    if session:
        mode = session["mode"]
        default_model = settings.google_model if mode == "google" else settings.lmstudio_model
        return {
            "connected": True,
            "mode": mode,
            "provider": "Google AI Studio" if mode == "google" else "LM Studio",
            "model": session["model"] or default_model,
            "key_masked": MASK if mode == "google" else None,
            "expires_in": BYOK_TTL_SECONDS,
            "ttl_minutes": BYOK_TTL_SECONDS // 60,
        }
    if settings.ai_state == "live":
        return {
            "connected": True,
            "mode": "server",
            "provider": "Server default",
            "model": settings.gemma_model,
            "key_masked": MASK,
            "expires_in": None,
            "ttl_minutes": BYOK_TTL_SECONDS // 60,
        }
    return {"connected": False, "ttl_minutes": BYOK_TTL_SECONDS // 60}


@router.delete("/session/provider", status_code=204)
async def clear_session_provider(request: Request, user_id: str = Depends(current_user)):
    request.app.state.byok.pop(user_id, None)


class ModelsIn(BaseModel):
    mode: Literal["lmstudio", "google"]
    api_key: str = Field(default="", max_length=512)


@router.post("/session/models")
async def list_models(body: ModelsIn, settings: Settings = Depends(get_config)):
    """Models for the dropdown: what the user's Google key can use, or what LM Studio has loaded."""
    if body.mode == "google":
        return await _google_models(body.api_key.strip().strip("\"'"), settings)
    url = settings.lmstudio_url.rsplit("/chat/completions", 1)[0] + "/models"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            data = (await client.get(url)).json()["data"]
        ids = [m["id"] for m in data if "embed" not in m["id"].lower()]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.info("Could not list LM Studio models")
        return {
            "models": [],
            "default": settings.lmstudio_model,
            "error": "Can't reach LM Studio. Start its server and load a model, then press Refresh.",
        }
    return {"models": ids, "default": ids[0] if ids else settings.lmstudio_model}


async def _google_models(key: str, settings: Settings) -> dict:
    fallback = {"models": [], "default": ""}
    if len(key) < 8:
        return {**fallback, "error": "Paste your API key to load the models available to you."}
    url = settings.google_url.split("/openai/")[0] + "/models?pageSize=200"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"x-goog-api-key": key})
        if resp.status_code in (400, 401, 403):
            return {**fallback, "error": "Google rejected the API key. Check that it is correct and enabled."}
        resp.raise_for_status()
        items = resp.json()["models"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        logger.info("Could not list Google models")
        return {**fallback, "error": "Couldn't load your model list from Google. Check your connection and press Refresh."}
    ids = sorted(
        (m["name"].removeprefix("models/") for m in items
         if "gemma" in m["name"].lower() and "generateContent" in m.get("supportedGenerationMethods", [])),
        reverse=True,
    )
    if not ids:
        return {**fallback, "error": "No Gemma models are available to this key in Google AI Studio."}
    default = settings.google_model if settings.google_model in ids else ids[0]
    return {"models": ids, "default": default}
