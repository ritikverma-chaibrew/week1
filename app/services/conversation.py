import asyncio
import logging

from app.models.conversation import FOCUSES, FREE_OPENING, SCENARIOS, StartPractice
from app.models.feedback import CoachResponse, EnglishEvaluation
from app.models.user import utcnow
from app.services import memory
from app.services.ai.base import AIError, AIProvider, ChatTurn, CoachContext

logger = logging.getLogger(__name__)


class ConversationNotFound(Exception):
    pass


async def _build_context(db, user_id: str, conversation: dict, history_limit: int) -> CoachContext:
    profile = await memory.get_profile(db, user_id)
    scenario = SCENARIOS.get(conversation.get("scenario") or "")
    cursor = (
        db.messages.find({"conversation_id": conversation["_id"]})
        .sort("created_at", -1)
        .limit(history_limit)
    )
    recent = list(reversed(await cursor.to_list(history_limit)))
    return CoachContext(
        mode=conversation["mode"],
        scenario_title=scenario[0] if scenario else None,
        scenario_prompt=scenario[1] if scenario else None,
        focus=conversation.get("focus"),
        recurring_mistakes=memory.describe_recurring(profile),
        history=[ChatTurn(m["role"], m["content"]) for m in recent],
    )


async def _store_message(db, conversation_id: str, role: str, content: str, **extra) -> dict:
    doc = {
        "_id": memory.new_id(),
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "created_at": utcnow(),
        **extra,
    }
    await db.messages.insert_one(doc)
    return doc


async def start_conversation(
    db, provider_factory, user_id: str, request: StartPractice, history_limit: int
) -> dict:
    """Create a conversation with an opening coach message.

    `provider_factory` is only called when the opener needs the model, so free
    conversation and workplace scenarios can be browsed without AI credentials.
    """
    focus = request.focus if request.mode == "targeted_practice" else None
    scenario = request.scenario if request.mode == "workplace_english" else None
    notice = None

    if request.mode == "workplace_english":
        scenario = scenario or "daily_standup"
        opening = SCENARIOS[scenario][1]
    elif request.mode == "targeted_practice":
        focus = focus or "recurring_mistakes"
        profile = await memory.get_profile(db, user_id)
        if focus == "recurring_mistakes" and not memory.top_recurring(profile):
            focus = "grammar"
            notice = "No recurring mistakes yet, so we'll start with general grammar practice."
        context = CoachContext(
            mode="targeted_practice",
            focus=focus,
            recurring_mistakes=memory.describe_recurring(profile),
        )
        opening = await provider_factory().generate_practice(context)
    else:
        opening = FREE_OPENING

    now = utcnow()
    conversation = {
        "_id": memory.new_id(),
        "user_id": user_id,
        "mode": request.mode,
        "scenario": scenario,
        "focus": focus,
        "created_at": now,
        "updated_at": now,
    }
    await db.conversations.insert_one(conversation)
    await _store_message(db, conversation["_id"], "assistant", opening)
    return {
        "conversation": _public_conversation(conversation),
        "messages": [{"role": "assistant", "content": opening}],
        "notice": notice,
    }


def _public_conversation(c: dict) -> dict:
    return {
        "id": c["_id"],
        "mode": c["mode"],
        "scenario": c.get("scenario"),
        "focus": c.get("focus"),
        "title": memory.session_title(c),
        "focus_label": FOCUSES.get(c.get("focus") or ""),
        "created_at": c["created_at"].isoformat(),
    }


async def _owned_conversation(db, user_id: str, conversation_id: str) -> dict:
    conversation = await db.conversations.find_one({"_id": conversation_id, "user_id": user_id})
    if not conversation:
        raise ConversationNotFound()
    return conversation


async def get_conversation(db, user_id: str, conversation_id: str) -> dict:
    conversation = await _owned_conversation(db, user_id, conversation_id)
    docs = await db.messages.find({"conversation_id": conversation_id}).sort("created_at", 1).to_list(500)
    return {
        "conversation": _public_conversation(conversation),
        "messages": [
            {"role": d["role"], "content": d["content"], "feedback": d.get("feedback")}
            for d in docs
        ],
    }


async def _evaluate_safely(provider: AIProvider, context: CoachContext, text: str) -> EnglishEvaluation | None:
    try:
        return await provider.evaluate_english(context, text)
    except AIError as exc:
        logger.warning("Evaluation unavailable: %s", type(exc).__name__)
        return None


async def send_message(
    db, provider: AIProvider, user_id: str, conversation_id: str, text: str, history_limit: int
) -> dict:
    conversation = await _owned_conversation(db, user_id, conversation_id)
    context = await _build_context(db, user_id, conversation, history_limit)

    reply, evaluation = await asyncio.gather(
        provider.generate_response(context, text),
        _evaluate_safely(provider, context, text),
    )
    feedback_available = evaluation is not None
    evaluation = evaluation or EnglishEvaluation(corrected_text=text)

    # A failed evaluation must not count as practice, or progress fills with empty data.
    patterns = (
        await memory.record_evaluation(db, user_id, conversation_id, evaluation)
        if feedback_available
        else []
    )
    coach = CoachResponse(
        response=reply, evaluation=evaluation, practice_suggestion=evaluation.practice_suggestion
    )
    feedback = {
        "available": feedback_available,
        "corrected_text": evaluation.corrected_text,
        "changed": evaluation.corrected_text.strip() != text,
        "mistakes": [m.model_dump() for m in evaluation.mistakes],
        "strengths": evaluation.strengths,
        "practice_suggestion": coach.practice_suggestion,
        "patterns": patterns,
    }
    await _store_message(db, conversation_id, "user", text, feedback=feedback)
    await _store_message(db, conversation_id, "assistant", coach.response)
    await db.conversations.update_one({"_id": conversation_id}, {"$set": {"updated_at": utcnow()}})
    return {"reply": coach.response, "feedback": feedback}
