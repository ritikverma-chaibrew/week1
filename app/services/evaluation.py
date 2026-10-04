"""Prompt construction and structured-output parsing for the AI coach."""

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.models.conversation import FOCUSES
from app.models.feedback import SKILL_KEYS
from app.services.ai.base import AIResponseError, CoachContext

T = TypeVar("T", bound=BaseModel)

COACH_PERSONA = """You are an English communication coach for a software engineer who \
understands English reasonably well but struggles to express ideas naturally and \
confidently at work.
Principles:
- Keep the conversation natural and practical (workplace English over academic grammar).
- Do not over-correct; ignore tiny stylistic differences.
- Preserve the learner's own voice; never make it overly formal.
- Be warm and encouraging; this is not an exam.
- Never mention databases, IDs or how you store information."""


def _context_block(ctx: CoachContext) -> str:
    lines = []
    if ctx.scenario_title:
        lines.append(f"Current practice: {ctx.scenario_title} - {ctx.scenario_prompt}")
    elif ctx.mode == "targeted_practice" and ctx.focus:
        lines.append(f"Current practice: targeted practice on {FOCUSES.get(ctx.focus, ctx.focus)}")
    else:
        lines.append("Current practice: free conversation")
    if ctx.recurring_mistakes:
        lines.append("Known recurring weaknesses of this learner:")
        lines.extend(f"- {item}" for item in ctx.recurring_mistakes)
    return "\n".join(lines)


def build_reply_system_prompt(ctx: CoachContext) -> str:
    return (
        f"{COACH_PERSONA}\n\n{_context_block(ctx)}\n\n"
        "Reply to the learner's latest message as a conversation partner in 2-4 short "
        "sentences and keep the conversation going with one question or next step. "
        "If a known recurring weakness appears in their message, gently invite them to "
        "try that sentence again. Reply with plain text only, no JSON."
    )


def build_evaluation_system_prompt(ctx: CoachContext) -> str:
    return (
        f"{COACH_PERSONA}\n\n{_context_block(ctx)}\n\n"
        "Evaluate ONLY the learner's latest message. Return a single JSON object and "
        "nothing else, with exactly these keys:\n"
        '{"corrected_text": "natural corrected version of the message",\n'
        ' "mistakes": [{"category": "past_tense|present_perfect|articles|prepositions|'
        "subject_verb_agreement|word_order|pluralization|verb_form|sentence_fragment|"
        'unnatural_phrase|word_choice|workplace_tone",\n'
        '   "original": "the faulty phrase", "correction": "the fixed phrase",\n'
        '   "explanation": "one short sentence", "severity": "minor|moderate|major"}],\n'
        ' "strengths": ["short phrase"],\n'
        + ' "scores": {' + ", ".join(f'"{k}": 75' for k in SKILL_KEYS) + "},\n"
        ' "practice_suggestion": "one short instruction to retry or practise, or null"}\n'
        "Each score is a single integer from 0 to 100 (the 75s above are placeholders: "
        "replace them with your own numbers, never write a range). "
        "Use an empty mistakes list when the English is fine. Report at most 3 of the "
        "most meaningful mistakes. Use double quotes and valid JSON."
    )


def build_practice_system_prompt(ctx: CoachContext) -> str:
    return (
        f"{COACH_PERSONA}\n\n{_context_block(ctx)}\n\n"
        "Write ONE short practice prompt (2-3 sentences) that starts a conversation "
        "and naturally requires the learner to use their weak areas. For example, if "
        "past tense is a weakness, ask about something they did yesterday. Plain text "
        "only. Do not list rules."
    )


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(raw: str) -> str:
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise AIResponseError("The model did not return JSON.")
    return text[start : end + 1]


def parse_model(raw: str, model: type[T]) -> T:
    try:
        return model.model_validate_json(extract_json(raw))
    except (ValidationError, json.JSONDecodeError) as exc:
        raise AIResponseError("The model returned invalid structured output.") from exc
