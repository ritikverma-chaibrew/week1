import re

from pydantic import BaseModel, Field, field_validator

SKILL_KEYS = ("grammar", "vocabulary", "natural_english", "professional_english")

# Extensible taxonomy: unknown subtypes from the model are still accepted (normalised).
SUBTYPE_TO_PRIMARY = {
    "past_tense": "grammar",
    "present_perfect": "grammar",
    "articles": "grammar",
    "prepositions": "grammar",
    "subject_verb_agreement": "grammar",
    "pluralization": "grammar",
    "verb_form": "grammar",
    "word_order": "sentence_structure",
    "sentence_fragment": "sentence_structure",
    "unnatural_phrase": "natural_english",
    "word_choice": "vocabulary",
    "workplace_tone": "professional_english",
}

SEVERITIES = ("minor", "moderate", "major")


def normalize_category(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "other"


def category_label(category: str) -> str:
    return category.replace("_", " ").capitalize()


class Mistake(BaseModel):
    category: str
    original: str
    correction: str
    explanation: str
    severity: str = "minor"

    @field_validator("category")
    @classmethod
    def _normalize_category(cls, value: str) -> str:
        return normalize_category(value)

    @field_validator("severity")
    @classmethod
    def _normalize_severity(cls, value: str) -> str:
        value = value.strip().lower()
        return value if value in SEVERITIES else "minor"

    @property
    def primary_category(self) -> str:
        return SUBTYPE_TO_PRIMARY.get(self.category, "grammar")


class EnglishEvaluation(BaseModel):
    corrected_text: str
    mistakes: list[Mistake] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    scores: dict[str, int] = Field(default_factory=dict)
    practice_suggestion: str | None = None

    @field_validator("scores")
    @classmethod
    def _clamp_scores(cls, scores: dict[str, int]) -> dict[str, int]:
        return {k: max(0, min(100, v)) for k, v in scores.items() if k in SKILL_KEYS}


class CoachResponse(BaseModel):
    response: str
    evaluation: EnglishEvaluation
    practice_suggestion: str | None = None
