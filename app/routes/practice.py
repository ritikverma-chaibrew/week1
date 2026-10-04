from fastapi import APIRouter

from app.models.conversation import FOCUSES, MODES, SCENARIOS

router = APIRouter(prefix="/api/practice")


@router.get("/modes")
async def practice_modes():
    return {
        "modes": [{"id": k, "label": v} for k, v in MODES.items()],
        "focuses": [{"id": k, "label": v} for k, v in FOCUSES.items()],
        "scenarios": [
            {"id": k, "title": title, "prompt": prompt} for k, (title, prompt) in SCENARIOS.items()
        ],
    }
