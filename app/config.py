from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

AIState = Literal["live", "unconfigured", "invalid"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    mongodb_uri: str = "mongodb://localhost:27017"
    database_name: str = "english_coach"

    ai_provider: str = "gemma"
    gemma_api_url: str | None = None
    gemma_api_key: str | None = None
    gemma_model: str | None = None
    ai_timeout_seconds: float = 30.0

    secret_key: str = "dev-only-change-me"
    max_context_messages: int = 8

    @property
    def ai_state(self) -> AIState:
        """live: usable, unconfigured: nothing set, invalid: partially/incorrectly set."""
        url, key = _clean(self.gemma_api_url), _clean(self.gemma_api_key)
        if not url and not key:
            return "unconfigured"
        if self.ai_provider != "gemma" or not url or not key:
            return "invalid"
        if not url.startswith(("http://", "https://")):
            return "invalid"
        return "live"


def _clean(value: str | None) -> str:
    return (value or "").strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
