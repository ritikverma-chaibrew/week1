import re

from app.models.feedback import EnglishEvaluation, Mistake
from app.services.ai.base import AIProvider, AIRequestError, CoachContext

_PRESENT_FOR_PAST = re.compile(r"\byesterday\b.*\b(go|buy|see|have|do|make)\b", re.IGNORECASE)


class MockAIProvider(AIProvider):
    """Deterministic provider for tests: flags a present-tense verb after 'yesterday'."""

    def __init__(
        self,
        evaluation: EnglishEvaluation | None = None,
        reply: str = "Thanks for sharing! What happened next?",
        fail: bool = False,
    ):
        self.evaluation = evaluation
        self.reply = reply
        self.fail = fail
        self.contexts: list[CoachContext] = []

    async def generate_response(self, context: CoachContext, user_message: str) -> str:
        self.contexts.append(context)
        if self.fail:
            raise AIRequestError()
        return self.reply

    async def evaluate_english(
        self, context: CoachContext, user_message: str
    ) -> EnglishEvaluation:
        if self.fail:
            raise AIRequestError()
        if self.evaluation:
            return self.evaluation
        if _PRESENT_FOR_PAST.search(user_message):
            return EnglishEvaluation(
                corrected_text="Yesterday, I went to the market and bought some vegetables.",
                mistakes=[
                    Mistake(
                        category="past_tense",
                        original="I go",
                        correction="I went",
                        explanation="Use the past tense for a completed action in the past.",
                        severity="moderate",
                    )
                ],
                strengths=["clear sentence intent"],
                scores={"grammar": 60, "natural_english": 65},
                practice_suggestion="Try the sentence again using the past tense.",
            )
        return EnglishEvaluation(
            corrected_text=user_message,
            strengths=["clear sentence intent"],
            scores={"grammar": 85, "vocabulary": 80, "natural_english": 80},
        )

    async def generate_practice(self, context: CoachContext) -> str:
        if self.fail:
            raise AIRequestError()
        self.contexts.append(context)
        weak = context.recurring_mistakes[0] if context.recurring_mistakes else "grammar"
        return f"Let's practise {weak}. Tell me what you did yesterday."
