import hashlib
import hmac
import re
import time
import uuid

from fastapi import Depends, Request, Response

from app.config import Settings, get_settings
from app.services import memory
from app.services.ai import build_provider
from app.services.ai.base import AIProvider

COOKIE = "epa_uid"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
BYOK_TTL_SECONDS = 60 * 60
_UID = re.compile(r"^u-[0-9a-f]{32}$")


def _sign(value: str, secret: str) -> str:
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:24]


def _verified_uid(cookie: str | None, secret: str) -> str | None:
    if not cookie or "." not in cookie:
        return None
    uid, _, signature = cookie.partition(".")
    if _UID.match(uid) and hmac.compare_digest(signature, _sign(uid, secret)):
        return uid
    return None


def get_db(request: Request):
    return request.app.state.db


def get_config() -> Settings:
    return get_settings()


def peek_user(request: Request, settings: Settings) -> str | None:
    """Identify the caller without touching the database or setting cookies."""
    return _verified_uid(request.cookies.get(COOKIE), settings.secret_key)


async def current_user(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_config),
    db=Depends(get_db),
) -> str:
    """Anonymous learner id from a signed cookie, ."""
    user_id = peek_user(request, settings)
    if not user_id:
        user_id = f"u-{uuid.uuid4().hex}"
        response.set_cookie(
            COOKIE,
            f"{user_id}.{_sign(user_id, settings.secret_key)}",
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    await memory.ensure_user(db, user_id)
    return user_id


def _byok_key(request: Request, user_id: str) -> str | None:
    entry = request.app.state.byok.get(user_id)
    if not entry:
        return None
    key, expires = entry
    if expires < time.monotonic():
        request.app.state.byok.pop(user_id, None)
        return None
    return key


def get_provider_factory(
    request: Request,
    user_id: str = Depends(current_user),
    settings: Settings = Depends(get_config),
):
    """Returns a callable so the provider is only resolved when AI is actually needed."""

    def factory() -> AIProvider:
        override = getattr(request.app.state, "provider", None)
        if override is not None:  # injected provider (tests)
            return override
        return build_provider(settings, _byok_key(request, user_id))

    return factory


def ai_state_for(request: Request, user_id: str | None, settings: Settings) -> str:
    if getattr(request.app.state, "provider", None) is not None:
        return "live"
    if user_id and _byok_key(request, user_id) and (settings.gemma_api_url or "").strip():
        return "live"
    return settings.ai_state
