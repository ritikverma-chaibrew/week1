from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.models.feedback import EnglishEvaluation


class AIError(Exception):
    """Base class for AI failures; `message` is safe to show to users."""

    status_code = 503
    message = "The coach is temporarily unavailable. Please try again in a moment."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        self.message = message or self.message


class AIUnavailableError(AIError):
    message = (
        "AI provider unavailable. You can configure GEMMA_API_URL and GEMMA_API_KEY "
        "to enable live AI conversations."
    )


class AIConfigError(AIError):
    message = "Live AI is not configured correctly. Please check the Gemma provider settings."


class AIRateLimitError(AIError):
    status_code = 429
    message = "The coach is busy right now. Please wait a few seconds and try again."


class AIRequestError(AIError):
    """Timeouts and upstream HTTP failures."""


class AIResponseError(AIError):
    """The model answered, but not with usable structured output."""


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class CoachContext:
    """Everything the model needs to know, and nothing more (no IDs, no full history)."""

    mode: str = "free_conversation"
    scenario_title: str | None = None
    scenario_prompt: str | None = None
    focus: str | None = None
    recurring_mistakes: list[str] = field(default_factory=list)  # e.g. "past tense (12x)"
    history: list[ChatTurn] = field(default_factory=list)


class AIProvider(ABC):
    @abstractmethod
    async def generate_response(self, context: CoachContext, user_message: str) -> str:
        """Natural conversational reply to the learner's latest message."""

    @abstractmethod
    async def evaluate_english(
        self, context: CoachContext, user_message: str
    ) -> EnglishEvaluation:
        """Structured evaluation of the learner's English."""

    @abstractmethod
    async def generate_practice(self, context: CoachContext) -> str:
        """An opening practice prompt tailored to the focus and stored weaknesses."""
