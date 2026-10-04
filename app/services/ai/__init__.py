from app.config import Settings
from app.services.ai.base import AIConfigError, AIProvider, AIUnavailableError
from app.services.ai.gemma import GemmaProvider


def build_provider(settings: Settings, api_key: str | None = None) -> AIProvider:
    """Create the configured provider, or raise a user-safe AIError if it cannot be used."""
    key = (api_key or settings.gemma_api_key or "").strip()
    url = (settings.gemma_api_url or "").strip()
    if not url and not key:
        raise AIUnavailableError()
    if settings.ai_provider != "gemma" or not url.startswith(("http://", "https://")) or not key:
        raise AIConfigError()
    return GemmaProvider(url, key, settings.gemma_model, timeout=settings.ai_timeout_seconds)
