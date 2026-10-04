from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MODES = {
    "free_conversation": "Normal Conversation",
    "targeted_practice": "Targeted Practice",
    "workplace_english": "Workplace English",
}

FOCUSES = {
    "grammar": "Grammar",
    "natural_english": "Natural English",
    "vocabulary": "Vocabulary",
    "professional_english": "Professional English",
    "recurring_mistakes": "Recurring Mistakes",
}

FREE_OPENING = "Tell me about something interesting that happened today."

SCENARIOS = {
    "daily_standup": (
        "Daily Standup",
        "Your manager asks what you worked on yesterday, what you're doing today, "
        "and whether you have any blockers.",
    ),
    "explain_bug": (
        "Explain a Bug",
        "A teammate asks you to explain the bug you found in production: what happened, "
        "why it happened, and how you plan to fix it.",
    ),
    "code_review": (
        "Code Review",
        "You are reviewing a colleague's pull request. Give feedback on a function that "
        "works but is hard to read.",
    ),
    "ask_for_help": (
        "Ask for Help",
        "You have been stuck on a failing integration test for two hours. Ask a senior "
        "engineer for help and explain what you have already tried.",
    ),
    "manager_update": (
        "Manager Update",
        "Your manager asks for a quick update on your current task and whether it will be "
        "ready by Friday.",
    ),
    "client_meeting": (
        "Client Meeting",
        "A client asks why a feature they requested is delayed. Explain the situation "
        "and propose a new timeline.",
    ),
    "technical_presentation": (
        "Technical Presentation",
        "You are presenting a new caching design to the team. Introduce the problem and "
        "your proposed solution in a few sentences.",
    ),
    "disagree_professionally": (
        "Disagree Professionally",
        "A teammate proposes rewriting a service in a new language. You think it is too "
        "risky right now. Share your concerns politely.",
    ),
    "project_status": (
        "Give a Project Status Update",
        "In the weekly meeting, give a short status update: what is done, what is in "
        "progress, and any risks.",
    ),
}


class StartPractice(BaseModel):
    mode: Literal["free_conversation", "targeted_practice", "workplace_english"] = (
        "free_conversation"
    )
    scenario: str | None = None
    focus: str | None = None

    @field_validator("scenario")
    @classmethod
    def _known_scenario(cls, value: str | None) -> str | None:
        if value is not None and value not in SCENARIOS:
            raise ValueError("Unknown scenario.")
        return value

    @field_validator("focus")
    @classmethod
    def _known_focus(cls, value: str | None) -> str | None:
        if value is not None and value not in FOCUSES:
            raise ValueError("Unknown practice focus.")
        return value


class MessageIn(BaseModel):
    content: str = Field(max_length=2000)

    @field_validator("content")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Please write a message first.")
        return value


class ProviderIn(BaseModel):
    mode: Literal["lmstudio", "google"]
    api_key: str = Field(default="", max_length=512)
    model: str = Field(default="", max_length=120)

    @model_validator(mode="after")
    def _google_needs_key(self):
        if self.mode == "google" and len(self.api_key.strip()) < 8:
            raise ValueError("Paste your Google AI Studio API key to use Google.")
        return self
