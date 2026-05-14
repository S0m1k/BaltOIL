import uuid
import json
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError
from app.services.conversation_service import _check_access
from app.config import settings

logger = logging.getLogger(__name__)


async def send_message(
    db: AsyncSession,
    conv_id: uuid.UUID,
    text: str,
    actor: TokenUser,
    msg_type: str = "text",
    metadata: dict | None = None,
) -> Message:
    # Load conversation with participants
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.participants))
        .where(Conversation.id == conv_id, Conversation.is_archived == False)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversation not found")

    _check_access(conv, actor)

    msg = Message(
        conversation_id=conv_id,
        sender_id=actor.id,
        sender_role=actor.role,
        sender_name=actor.name,
        msg_type=msg_type,
        text=text,
        msg_metadata=metadata,
    )
    db.add(msg)

    # Update conversation updated_at
    from datetime import datetime, timezone
    from sqlalchemy import update as sa_update
    await db.execute(
        sa_update(Conversation)
        .where(Conversation.id == conv_id)
        .values(updated_at=datetime.now(timezone.utc))
    )

    await db.commit()
    await db.refresh(msg)

    # Publish to events:chat so notification_service can fan out to recipients
    participant_ids = [str(p.user_id) for p in conv.participants]
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.publish("events:chat", json.dumps({
                "event": "chat_message",
                "conv_id": str(conv_id),
                "sender_id": str(actor.id),
                "sender_name": actor.name,
                "body": text,
                "participant_ids": participant_ids,
            }))
        finally:
            await r.aclose()
    except Exception:
        logger.exception("Failed to publish chat event")

    return msg


async def get_messages(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
    limit: int = 50,
    before_id: uuid.UUID | None = None,
) -> list[Message]:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.participants))
        .where(Conversation.id == conv_id, Conversation.is_archived == False)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversation not found")

    _check_access(conv, actor)

    q = select(Message).where(
        Message.conversation_id == conv_id,
        Message.is_archived == False,
    )

    if before_id:
        # Cursor-based pagination: get messages before given message id
        ref_result = await db.execute(
            select(Message.created_at).where(Message.id == before_id)
        )
        ref_ts = ref_result.scalar_one_or_none()
        if ref_ts:
            q = q.where(Message.created_at < ref_ts)

    q = q.order_by(Message.created_at.desc()).limit(limit)
    msgs_result = await db.execute(q)
    msgs = msgs_result.scalars().all()
    return list(reversed(msgs))


async def delete_message(
    db: AsyncSession,
    msg_id: uuid.UUID,
    actor: TokenUser,
) -> None:
    result = await db.execute(
        select(Message).where(Message.id == msg_id, Message.is_archived == False)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise NotFoundError("Message not found")

    # Only sender or manager/admin can delete
    if msg.sender_id != actor.id and actor.role not in {"admin", "manager"}:
        raise ForbiddenError("Cannot delete this message")

    msg.is_archived = True
    await db.commit()
