from fastapi import APIRouter, Depends

from app.routes.deps import current_user, get_db
from app.services import memory

router = APIRouter(prefix="/api")


@router.get("/progress")
async def progress(db=Depends(get_db), user_id: str = Depends(current_user)):
    return await memory.progress_summary(db, user_id)


@router.get("/mistakes")
async def mistakes(db=Depends(get_db), user_id: str = Depends(current_user)):
    return {"mistakes": await memory.recent_mistakes(db, user_id)}
