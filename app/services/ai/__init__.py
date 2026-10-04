from app.config import Settings
from app.services.ai.base import AIConfigError, AIProvider, AIUnavailableError
from app.services.ai.gemma import GemmaProvider


def build_provider(settings: Settings, session: dict | None = None) -> AIProvider:
    """Create the provider for the learner's dropdown choice, else the server's .env settings.

    `session` is {"mode": "lmstudio" | "google", "api_key": str, "model": str}.
    """
    if session:
        model = (session.get("model") or "").strip()
        if session["mode"] == "lmstudio":
            return GemmaProvider(
                settings.lmstudio_url,
                "lm-studio",  # LM Studio ignores the key
                model or settings.lmstudio_model,
                timeout=settings.lmstudio_timeout_seconds,
                label="LM Studio",
            )
        return GemmaProvider(
            settings.google_url,
            session["api_key"],
            model or settings.google_model,
            timeout=settings.ai_timeout_seconds,
            label="Google AI Studio",
        )
    key = (settings.gemma_api_key or "").strip()
    url = (settings.gemma_api_url or "").strip()
    if not url and not key:
        raise AIUnavailableError()
    if settings.ai_provider != "gemma" or not url.startswith(("http://", "https://")) or not key:
        raise AIConfigError()
    return GemmaProvider(url, key, settings.gemma_model, timeout=settings.ai_timeout_seconds)
