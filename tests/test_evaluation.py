import asyncio
import json

import httpx
import pytest

from app.models.feedback import EnglishEvaluation
from app.services.ai.base import (
    AIConfigError,
    AIRateLimitError,
    AIRequestError,
    AIResponseError,
    ChatTurn,
    CoachContext,
)
from app.services.ai.gemma import GemmaProvider, to_chat_messages
from app.services.evaluation import parse_model

VALID = {
    "corrected_text": "Yesterday, I went to the market.",
    "mistakes": [
        {
            "category": "Past Tense",
            "original": "I go",
            "correction": "I went",
            "explanation": "Use the past tense.",
            "severity": "HIGH",
        }
    ],
    "strengths": ["clear intent"],
    "scores": {"grammar": 140, "unknown_skill": 5},
}


def test_valid_json_parses_and_normalises():
    result = parse_model(json.dumps(VALID), EnglishEvaluation)
    assert result.mistakes[0].category == "past_tense"
    assert result.mistakes[0].severity == "minor"
    assert result.scores == {"grammar": 100}


def test_fenced_json_with_chatter_parses():
    raw = "Sure!\n```json\n" + json.dumps(VALID) + "\n```"
    assert parse_model(raw, EnglishEvaluation).corrected_text.startswith("Yesterday")


@pytest.mark.parametrize("raw", ["not json at all", '{"corrected_text": 5}', "{broken"])
def test_invalid_output_raises(raw):
    with pytest.raises(AIResponseError):
        parse_model(raw, EnglishEvaluation)


def test_messages_alternate_and_fold_system_prompt():
    history = [ChatTurn("assistant", "Opener"), ChatTurn("user", "a"), ChatTurn("assistant", "b")]
    messages = to_chat_messages("SYSTEM", history, "c")
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert "SYSTEM" in messages[0]["content"] and "Opener" in messages[0]["content"]


def _provider(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return GemmaProvider("https://gemma.test/v1/chat/completions", "secret", "gemma-x", client=client)


def _completion(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_gemma_retries_once_on_invalid_json():
    calls = []

    def handler(request):
        calls.append(request)
        return _completion("oops" if len(calls) == 1 else json.dumps(VALID))

    result = asyncio.run(_provider(handler).evaluate_english(CoachContext(), "hi"))
    assert len(calls) == 2
    assert calls[0].headers["authorization"] == "Bearer secret"
    assert result.mistakes


def test_gemma_gives_up_after_second_invalid_json():
    provider = _provider(lambda request: _completion("still not json"))
    with pytest.raises(AIResponseError):
        asyncio.run(provider.evaluate_english(CoachContext(), "hi"))


@pytest.mark.parametrize(
    "status,error", [(429, AIRateLimitError), (401, AIConfigError), (500, AIRequestError)]
)
def test_gemma_http_errors_map_to_friendly_errors(status, error):
    provider = _provider(lambda request: httpx.Response(status))
    with pytest.raises(error):
        asyncio.run(provider.generate_response(CoachContext(), "hi"))


def test_gemma_timeout_maps_to_request_error():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AIRequestError):
        asyncio.run(_provider(handler).generate_response(CoachContext(), "hi"))
