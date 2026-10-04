from datetime import datetime, timezone

from pydantic import BaseModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecurringMistake(BaseModel):
    type: str
    frequency: int
    first_seen: datetime
    last_seen: datetime
