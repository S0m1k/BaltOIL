import uuid
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError
from app.services.conversation_service import _check_access
from app.services import ws_manager
from app.config import settings

logger = logging.getLogger(__name__)

# UUID нулей — sender_id для системных сообщений (Message.sender_id NOT NULL).
SYSTEM_SENDER_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")

_MSG_RATE_LIMIT = 60  # messages per minute per (user, conversation)


async def _check_message_rate(
    redis: aioredis.Redis,
    actor_id: uuid.UUID,
    conv_id: uuid.UUID,
) -> None:
    """Raise ForbiddenError if the user is sending too fast in this conversation."""
    key = f"msgrate:{actor_id}:{conv_id}"
    n = await redis.incr(key)
    if n == 1:
        await redis.expire(key, 60)
    if n > _MSG_RATE_LIMIT:
        raise ForbiddenError("Слишком много сообщений, подождите немного")


async def send_message(
    db: AsyncSession,
    conv_id: uuid.UUID,
    text: str,
    actor: TokenUser,
    redis: aioredis.Redis,
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
    await _check_message_rate(redis, actor.id, conv_id)

    # Staff (manager/admin) bypass the participant check in _check_access but are
    # not recorded in conversation_participants. Auto-enroll them on first message
    # so mark_read / unread badges and call participant lists work correctly.
    if actor.role in {"manager", "admin"}:
        already_in = any(p.user_id == actor.id for p in conv.participants)
        if not already_in:
            from datetime import datetime as _dt, timezone as _tz
            db.add(ConversationParticipant(
                conversation_id=conv_id,
                user_id=actor.id,
                user_role=actor.role,
                last_read_at=_dt.now(_tz.utc),
            ))
            await db.flush()
            await db.refresh(conv, ["participants"])

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

    # Publish to events:chat so notification_service can fan out to recipients.
    # Членство определяется snapshot-полями (client_id/driver_id), а не таблицей
    # participants (она наполняется лишь при ОТКРЫТИИ чата). Берём объединение,
    # иначе первое сообщение водителя в свежем заказ-чате не доходило бы до клиента,
    # ещё не открывавшего диалог. notification_service сам исключит отправителя.
    recipient_ids = {str(p.user_id) for p in conv.participants}
    if conv.client_id:
        recipient_ids.add(str(conv.client_id))
    if conv.driver_id:
        recipient_ids.add(str(conv.driver_id))
    participant_ids = list(recipient_ids)
    try:
        await redis.publish("events:chat", json.dumps({
            "event": "chat_message",
            "conv_id": str(conv_id),
            "sender_id": str(actor.id),
            "sender_name": actor.name,
            "body": text,
            "participant_ids": participant_ids,
        }))
    except Exception:
        logger.exception("Failed to publish chat event")

    return msg


async def post_system_message(
    db: AsyncSession,
    conv_id: uuid.UUID,
    text: str,
    redis: aioredis.Redis,
    metadata: dict | None = None,
) -> Message:
    """Вставить системное сообщение в диалог.
    Используется внутренними сервисами (call_service, future order_service)
    через /internal-эндпоинт с X-Internal-Secret. _check_access не вызывается —
    отправитель уже доверенный.

    Системные сообщения НЕ публикуются в events:chat (notification_service
    их не разносит как «новое сообщение»), но публикуются в chat:{conv_id}
    чтобы WS-клиенты увидели их мгновенно.
    """
    # Проверка существования и не-архивности диалога
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.is_archived == False  # noqa: E712
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversation not found")

    msg = Message(
        conversation_id=conv_id,
        sender_id=SYSTEM_SENDER_ID,
        sender_role="system",
        sender_name="Система",
        msg_type="system",
        text=text,
        msg_metadata=metadata,
    )
    db.add(msg)
    await db.execute(
        sa_update(Conversation)
        .where(Conversation.id == conv_id)
        .values(updated_at=datetime.now(timezone.utc))
    )
    await db.commit()
    await db.refresh(msg)

    # Мгновенная доставка в открытые WS — payload должен соответствовать
    # тому, что собирает websocket.py (см. _broadcast_payload).
    try:
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "id": str(msg.id),
            "conversation_id": str(msg.conversation_id),
            "sender_id": str(msg.sender_id),
            "sender_role": msg.sender_role,
            "sender_name": msg.sender_name,
            "msg_type": msg.msg_type,
            "text": msg.text,
            "metadata": msg.msg_metadata,
            "created_at": msg.created_at.isoformat(),
        }))
    except Exception:
        logger.exception("Failed to publish system message to WS channel")

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
