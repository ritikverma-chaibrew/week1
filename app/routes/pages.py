from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.routes.deps import ai_state_for, get_config, peek_user
from app.services.ai.base import AIConfigError, AIUnavailableError

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parents[2] / "templates")

AI_MESSAGES = {"unconfigured": AIUnavailableError.message, "invalid": AIConfigError.message}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@router.get("/health", include_in_schema=False)
@router.get("/api/health")
async def health(request: Request, settings: Settings = Depends(get_config)):
    state = ai_state_for(request, peek_user(request, settings), settings)
    return {"status": "ok", "ai": state, "ai_message": AI_MESSAGES.get(state)}
