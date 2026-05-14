"""
Dev seed for chat_service: creates conversations and messages.
FORBIDDEN on production (APP_ENV=production).
Run via: docker compose exec chat_service python /app/scripts/seed.py
"""
import asyncio
import os
import sys
import uuid
import hashlib
from datetime import datetime, timezone, timedelta

if os.environ.get("APP_ENV") == "production":
    print("ERROR: seed.py is FORBIDDEN on production", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

sys.path.insert(0, "/app")

from app.config import get_settings
from app.models import Conversation, ConversationType, ConversationParticipant, Message

settings = get_settings()

# Same fixed UUIDs as auth seed
USERS = {
    "manager1":   uuid.UUID("00000000-0000-0000-0000-000000000002"),
    "client_pre": uuid.UUID("00000000-0000-0000-0000-000000000011"),
    "client_del": uuid.UUID("00000000-0000-0000-0000-000000000012"),
}

now = datetime.now(timezone.utc)

CONV_IDS = {
    "conv_1": uuid.UUID("30000000-0000-0000-0000-000000000001"),
    "conv_2": uuid.UUID("30000000-0000-0000-0000-000000000002"),
}


def participants_hash(*user_ids: uuid.UUID) -> str:
    """Matches the hash used by the service."""
    sorted_ids = sorted(str(u) for u in user_ids)
    return hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()


CONVERSATIONS = [
    dict(
        id=CONV_IDS["conv_1"],
        type=ConversationType.CLIENT_SUPPORT,
        participants_hash=participants_hash(USERS["manager1"], USERS["client_pre"]),
        title="Поддержка: Клиент Предоплата",
        created_by_id=USERS["manager1"],
        created_by_role="manager",
    ),
    dict(
        id=CONV_IDS["conv_2"],
        type=ConversationType.CLIENT_SUPPORT,
        participants_hash=participants_hash(USERS["manager1"], USERS["client_del"]),
        title="Поддержка: Клиент По Факту",
        created_by_id=USERS["manager1"],
        created_by_role="manager",
    ),
]

PARTICIPANTS = [
    dict(id=uuid.UUID("40000000-0000-0000-0000-000000000001"), conversation_id=CONV_IDS["conv_1"], user_id=USERS["manager1"], user_role="manager"),
    dict(id=uuid.UUID("40000000-0000-0000-0000-000000000002"), conversation_id=CONV_IDS["conv_1"], user_id=USERS["client_pre"], user_role="client"),
    dict(id=uuid.UUID("40000000-0000-0000-0000-000000000003"), conversation_id=CONV_IDS["conv_2"], user_id=USERS["manager1"], user_role="manager"),
    dict(id=uuid.UUID("40000000-0000-0000-0000-000000000004"), conversation_id=CONV_IDS["conv_2"], user_id=USERS["client_del"], user_role="client"),
]

MESSAGES = [
    dict(id=uuid.UUID("50000000-0000-0000-0000-000000000001"),
         conversation_id=CONV_IDS["conv_1"], sender_id=USERS["client_pre"],
         sender_role="client", sender_name="Клиент Предоплата",
         text="Добрый день! Хотел уточнить статус моей заявки №ORD-2026-000001.",
         created_at=now - timedelta(hours=2)),
    dict(id=uuid.UUID("50000000-0000-0000-0000-000000000002"),
         conversation_id=CONV_IDS["conv_1"], sender_id=USERS["manager1"],
         sender_role="manager", sender_name="Менеджер Первый",
         text="Здравствуйте! Ваша заявка принята в работу, водитель будет назначен сегодня.",
         created_at=now - timedelta(hours=1, minutes=45)),
    dict(id=uuid.UUID("50000000-0000-0000-0000-000000000003"),
         conversation_id=CONV_IDS["conv_1"], sender_id=USERS["client_pre"],
         sender_role="client", sender_name="Клиент Предоплата",
         text="Спасибо, буду ждать.",
         created_at=now - timedelta(hours=1, minutes=30)),
    dict(id=uuid.UUID("50000000-0000-0000-0000-000000000004"),
         conversation_id=CONV_IDS["conv_2"], sender_id=USERS["manager1"],
         sender_role="manager", sender_name="Менеджер Первый",
         text="Ваша заявка №ORD-2026-000002 создана. Планируемая дата доставки — сегодня.",
         created_at=now - timedelta(minutes=30)),
]


async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        msg_ids = [m["id"] for m in MESSAGES]
        part_ids = [p["id"] for p in PARTICIPANTS]
        conv_ids = list(CONV_IDS.values())

        await session.execute(text("DELETE FROM messages WHERE id = ANY(:ids)"), {"ids": msg_ids})
        await session.execute(text("DELETE FROM conversation_participants WHERE id = ANY(:ids)"), {"ids": part_ids})
        await session.execute(text("DELETE FROM conversations WHERE id = ANY(:ids)"), {"ids": conv_ids})
        await session.commit()

        for c in CONVERSATIONS:
            session.add(Conversation(is_archived=False, **c))
        await session.commit()

        for p in PARTICIPANTS:
            session.add(ConversationParticipant(**p))
        await session.commit()

        for m in MESSAGES:
            session.add(Message(is_archived=False, **m))
        await session.commit()

    await engine.dispose()
    print(f"[seed:chat] Created {len(CONVERSATIONS)} conversations, {len(MESSAGES)} messages")


if __name__ == "__main__":
    asyncio.run(main())
