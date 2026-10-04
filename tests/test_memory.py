import asyncio
from datetime import timedelta

from app.models.feedback import EnglishEvaluation, Mistake
from app.models.user import utcnow
from app.services import memory


def past_tense(scores=None):
    return EnglishEvaluation(
        corrected_text="Yesterday I went.",
        mistakes=[Mistake(category="past_tense", original="go", correction="went", explanation="Past.")],
        strengths=["clear intent"],
        scores=scores or {"grammar": 60},
    )


def test_mistake_is_stored(db):
    asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    stored = db.mistakes.docs
    assert len(stored) == 1 and stored[0]["category"] == "past_tense" and stored[0]["user_id"] == "u1"


def test_repeated_mistakes_increase_frequency_and_flag_pattern(db):
    first = asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    second = asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    assert first == []  # a single occurrence is not yet a pattern
    assert second[0]["type"] == "past_tense" and second[0]["frequency"] == 2
    profile = asyncio.run(memory.get_profile(db, "u1"))
    assert profile["recurring_mistakes"][0]["frequency"] == 2
    assert memory.top_recurring(profile)[0]["type"] == "past_tense"
    assert "past tense" in memory.describe_recurring(profile)[0]


def test_skills_blend_instead_of_overwrite(db):
    asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense({"grammar": 50})))
    asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense({"grammar": 100})))
    assert asyncio.run(memory.get_profile(db, "u1"))["skills"]["grammar"] == 60


def test_new_user_has_no_fabricated_scores(db):
    summary = asyncio.run(memory.progress_summary(db, "fresh"))
    assert summary["has_data"] is False
    assert all(skill["score"] is None for skill in summary["skills"])
    assert summary["recurring_mistakes"] == []


def test_trend_only_reported_with_real_earlier_data(db):
    asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    assert asyncio.run(memory.progress_summary(db, "u1"))["recurring_mistakes"][0]["trend"] is None
    db.mistakes.docs[0]["created_at"] = utcnow() - timedelta(days=9)
    asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    trend = asyncio.run(memory.progress_summary(db, "u1"))["recurring_mistakes"][0]["trend"]
    assert trend == {"previous": 1, "current": 1}


def test_data_quality_levels(db):
    assert asyncio.run(memory.progress_summary(db, "u1"))["data_quality"]["level"] == "none"
    asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    quality = asyncio.run(memory.progress_summary(db, "u1"))["data_quality"]
    assert quality["level"] == "limited" and quality["evaluations"] == 1 and quality["message"]
    for _ in range(memory.MIN_RELIABLE_EVALUATIONS - 1):
        asyncio.run(memory.record_evaluation(db, "u1", "c1", past_tense()))
    quality = asyncio.run(memory.progress_summary(db, "u1"))["data_quality"]
    assert quality["level"] == "reliable" and quality["message"] == ""
