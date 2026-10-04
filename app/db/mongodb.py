from pymongo import AsyncMongoClient

from app.config import Settings

INDEXES = {
    "messages": "conversation_id",
    "conversations": "user_id",
    "mistakes": "user_id",
    "learning_profiles": "user_id",
}


def connect(settings: Settings) -> tuple[AsyncMongoClient, object]:
    client = AsyncMongoClient(
        settings.mongodb_uri, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    return client, client[settings.database_name]


async def ensure_indexes(db) -> None:
    for collection, field in INDEXES.items():
        await db[collection].create_index(field, unique=collection == "learning_profiles")
