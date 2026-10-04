import asyncio
import logging
import re
import time

import httpx

from app.models.feedback import EnglishEvaluation
from app.services import evaluation as prompts
from app.services.ai.base import (
    AIConfigError,
    AIProvider,
    AIRateLimitError,
    AIRequestError,
    AIResponseError,
    ChatTurn,
    CoachContext,
)

logger = logging.getLogger(__name__)

REPAIR_INSTRUCTION = (
    "Your previous answer was not valid JSON. Reply again with ONLY the JSON object."
)


MAX_ATTEMPTS = 3
THOUGHT_HEADROOM = 1500
_THOUGHT_RE = re.compile(r"<thought>.*?</thought>", re.DOTALL)


def strip_thoughts(text: str) -> str:
    """Drop Gemma's reasoning block; an unclosed one means the reply was cut off."""
    text = _THOUGHT_RE.sub("", text)
    if "<thought>" in text:
        text = text.split("<thought>", 1)[0]
    return text.strip()


def to_chat_messages(system: str, history: list[ChatTurn], user_message: str) -> list[dict]:
    """Build strictly alternating user/assistant turns.

    Gemma chat templates reject a separate system role and require alternation, so
    the instructions are folded into the first user turn.
    """
    turns = [ChatTurn(t.role, t.content) for t in history] + [ChatTurn("user", user_message)]
    preface = system
    if turns[0].role == "assistant":  # e.g. the scenario opener
        preface += f"\n\nThe conversation began with the coach saying: {turns.pop(0).content}"
    merged: list[dict] = []
    for turn in turns:
        if merged and merged[-1]["role"] == turn.role:
            merged[-1]["content"] += "\n" + turn.content
        else:
            merged.append({"role": turn.role, "content": turn.content})
    merged[0]["content"] = f"{preface}\n\n---\n\n{merged[0]['content']}"
    return merged


class GemmaProvider(AIProvider):
    """Hosted Gemma behind an OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        api_url: str,
        api_key: str,
        model: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ):
        self._url = api_url
        self._key = api_key
        self._model = model or "gemma"
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def _complete(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        # Gemma 4 spends part of the budget on a <thought> block, so leave headroom.
        max_tokens += THOUGHT_HEADROOM
        for attempt in range(1, MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                resp = await self._client.post(
                    self._url,
                    headers={"Authorization": f"Bearer {self._key}"},
                    json={
                        "model": self._model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
            except httpx.TimeoutException as exc:
                logger.warning("Gemma request timed out")
                raise AIRequestError() from exc
            except httpx.HTTPError as exc:
                logger.warning("Gemma request failed: %s", type(exc).__name__)
                raise AIRequestError() from exc
            logger.info("Gemma call %s in %.2fs", resp.status_code, time.perf_counter() - started)

            if resp.status_code in (500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
                await asyncio.sleep(0.5 * attempt)  # transient upstream error
                continue
            break

        if resp.status_code == 429:
            raise AIRateLimitError()
        if resp.status_code in (401, 403, 404):
            raise AIConfigError()
        if resp.status_code >= 400:
            raise AIRequestError()
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            logger.warning("Unexpected Gemma response shape")
            raise AIResponseError() from exc
        return strip_thoughts(content or "")

    async def generate_response(self, context: CoachContext, user_message: str) -> str:
        system = prompts.build_reply_system_prompt(context)
        messages = to_chat_messages(system, context.history, user_message)
        reply = await self._complete(messages, temperature=0.7, max_tokens=400)
        if not reply:
            raise AIResponseError()
        return reply

    async def evaluate_english(
        self, context: CoachContext, user_message: str
    ) -> EnglishEvaluation:
        system = prompts.build_evaluation_system_prompt(context)
        messages = to_chat_messages(system, [], f"Learner's message:\n{user_message}")
        raw = await self._complete(messages, temperature=0.2, max_tokens=700)
        try:
            return prompts.parse_model(raw, EnglishEvaluation)
        except AIResponseError:
            logger.info("Invalid evaluation JSON, retrying once")
        retry = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": REPAIR_INSTRUCTION},
        ]
        raw = await self._complete(retry, temperature=0.0, max_tokens=700)
        return prompts.parse_model(raw, EnglishEvaluation)

    async def generate_practice(self, context: CoachContext) -> str:
        system = prompts.build_practice_system_prompt(context)
        messages = to_chat_messages(system, [], "Please give me a practice prompt.")
        prompt = await self._complete(messages, temperature=0.8, max_tokens=250)
        if not prompt:
            raise AIResponseError()
        return prompt
