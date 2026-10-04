"""Persistent learning memory: stored mistakes, recurring patterns, skill indicators."""

import uuid
from datetime import datetime, timedelta

from app.models.conversation import MODES, SCENARIOS
from app.models.feedback import SKILL_KEYS, EnglishEvaluation, category_label
from app.models.user import utcnow

SKILL_LABELS = {
    "grammar": "Grammar",
    "vocabulary": "Vocabulary",
    "natural_english": "Natural English",
    "professional_english": "Professional English",
}
EMA_WEIGHT = 0.2
MAX_STRENGTHS = 6
MIN_RELIABLE_EVALUATIONS = 5
DISCLAIMER = (
    "Personal learning indicators: approximate progress signals, "
    "not a certified proficiency score."
)


def data_quality(evaluations: int) -> dict:
    """How much real data backs the progress numbers: none, limited or reliable."""
    if evaluations <= 0:
        level, message = "none", "Not enough data yet. Send a few messages in a practice session and your progress will appear here."
    elif evaluations < MIN_RELIABLE_EVALUATIONS:
        level = "limited"
        message = (
            f"Based on only {evaluations} evaluated message{'s' if evaluations != 1 else ''}. "
            f"Keep practicing: progress becomes more reliable after about {MIN_RELIABLE_EVALUATIONS} messages."
        )
    else:
        level, message = "reliable", ""
    return {
        "level": level,
        "evaluations": evaluations,
        "needed": MIN_RELIABLE_EVALUATIONS,
        "message": message,
    }


def new_id() -> str:
    return uuid.uuid4().hex


async def ensure_user(db, user_id: str) -> None:
    if await db.users.find_one({"_id": user_id}):
        return
    now = utcnow()
    await db.users.update_one(
        {"_id": user_id},
        {"$setOnInsert": {"name": "Learner", "created_at": now, "updated_at": now}},
        upsert=True,
    )


async def get_profile(db, user_id: str) -> dict:
    profile = await db.learning_profiles.find_one({"user_id": user_id})
    if profile:
        profile.setdefault("evaluation_count", 0)
        return profile
    return {
        "user_id": user_id,
        "skills": {},
        "recurring_mistakes": [],
        "strengths": [],
        "evaluation_count": 0,
    }


def top_recurring(profile: dict, limit: int = 3) -> list[dict]:
    ranked = sorted(profile["recurring_mistakes"], key=lambda m: m["frequency"], reverse=True)
    return [m for m in ranked if m["frequency"] >= 2][:limit]


def describe_recurring(profile: dict, limit: int = 3) -> list[str]:
    return [
        f"{category_label(m['type']).lower()} (seen {m['frequency']} times)"
        for m in top_recurring(profile, limit)
    ]


def _blend(old: float | None, new: int) -> int:
    return new if old is None else round(old * (1 - EMA_WEIGHT) + new * EMA_WEIGHT)


async def record_evaluation(
    db, user_id: str, conversation_id: str, evaluation: EnglishEvaluation
) -> list[dict]:
    """Persist mistakes, update the learning profile, return detected recurring patterns."""
    profile = await get_profile(db, user_id)
    now = utcnow()
    counts = {m["type"]: m for m in profile["recurring_mistakes"]}
    patterns: dict[str, dict] = {}

    for mistake in evaluation.mistakes:
        await db.mistakes.insert_one(
            {
                "_id": new_id(),
                "user_id": user_id,
                "conversation_id": conversation_id,
                "category": mistake.category,
                "primary_category": mistake.primary_category,
                "original": mistake.original,
                "correction": mistake.correction,
                "explanation": mistake.explanation,
                "severity": mistake.severity,
                "created_at": now,
            }
        )
        entry = counts.setdefault(
            mistake.category,
            {"type": mistake.category, "frequency": 0, "first_seen": now, "last_seen": now},
        )
        entry["frequency"] += 1
        entry["last_seen"] = now
        if entry["frequency"] >= 2:
            patterns[mistake.category] = {
                "type": mistake.category,
                "label": category_label(mistake.category),
                "frequency": entry["frequency"],
            }

    skills = dict(profile["skills"])
    for key, score in evaluation.scores.items():
        skills[key] = _blend(skills.get(key), score)
    strengths = list(dict.fromkeys(evaluation.strengths + profile["strengths"]))[:MAX_STRENGTHS]

    await db.learning_profiles.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "skills": skills,
                "recurring_mistakes": list(counts.values()),
                "strengths": strengths,
                "evaluation_count": profile["evaluation_count"] + 1,
                "updated_at": now,
            },
            "$setOnInsert": {"_id": new_id()},
        },
        upsert=True,
    )
    return list(patterns.values())


def _trend(mistakes: list[dict], mistake_type: str, now: datetime) -> dict | None:
    """Last 7 days vs the 7 days before; only reported when real earlier data exists."""
    week = timedelta(days=7)
    current = previous = 0
    for m in mistakes:
        if m["category"] != mistake_type:
            continue
        age = now - m["created_at"]
        if age <= week:
            current += 1
        elif age <= 2 * week:
            previous += 1
    return {"previous": previous, "current": current} if previous else None


def session_title(conversation: dict) -> str:
    if conversation.get("scenario") in SCENARIOS:
        return SCENARIOS[conversation["scenario"]][0]
    return MODES.get(conversation["mode"], "Practice")


async def progress_summary(db, user_id: str) -> dict:
    profile = await get_profile(db, user_id)
    now = utcnow()
    mistakes = await db.mistakes.find({"user_id": user_id}).to_list(1000)
    conversations = (
        await db.conversations.find({"user_id": user_id}).sort("updated_at", -1).limit(5).to_list(5)
    )
    recurring = sorted(profile["recurring_mistakes"], key=lambda m: m["frequency"], reverse=True)
    return {
        "has_data": profile["evaluation_count"] > 0,
        "data_quality": data_quality(profile["evaluation_count"]),
        "disclaimer": DISCLAIMER,
        "skills": [
            {"key": k, "label": SKILL_LABELS[k], "score": profile["skills"].get(k)}
            for k in SKILL_KEYS
        ],
        "recurring_mistakes": [
            {
                "type": m["type"],
                "label": category_label(m["type"]),
                "frequency": m["frequency"],
                "last_seen": m["last_seen"].isoformat(),
                "trend": _trend(mistakes, m["type"], now),
            }
            for m in recurring[:8]
        ],
        "strengths": profile["strengths"],
        "recent_sessions": [
            {
                "id": c["_id"],
                "title": session_title(c),
                "updated_at": c["updated_at"].isoformat(),
            }
            for c in conversations
        ],
    }


async def recent_mistakes(db, user_id: str, limit: int = 50) -> list[dict]:
    cursor = db.mistakes.find({"user_id": user_id}).sort("created_at", -1).limit(limit)
    return [
        {
            "category": d["category"],
            "label": category_label(d["category"]),
            "original": d["original"],
            "correction": d["correction"],
            "explanation": d["explanation"],
            "created_at": d["created_at"].isoformat(),
        }
        for d in await cursor.to_list(limit)
    ]
