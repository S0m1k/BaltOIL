"""Conversation service — snapshot-based membership model.

Three conversation kinds:
  client_manager      — one per client; managers/admins see all of them.
  client_driver_order — one per active order; client + assigned driver.
  staff_group         — three pre-created groups: general, drivers, managers.

Membership is enforced by snapshot fields in the Conversation row (client_id,
driver_id, order_id, group_code) — no RPC to auth_service needed for access checks.
ConversationParticipant is kept only for last_read_at (unread counters).
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, and_, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

from app.models.conversation import Conversation, ConversationParticipant, ConversationKind
from app.models.message import Message
from app.schemas.message import MessageResponse
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError
from app.services import auth_client

# UUID used as sender_id for system messages
_SYSTEM_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

STAFF_GROUPS = ("general", "drivers", "managers")

MANAGER_ROLES = {"admin", "manager"}


# ─────────────────────────────────────────────────────────────────────────────
# Access control
# ─────────────────────────────────────────────────────────────────────────────

def _check_access(conv: Conversation, actor: TokenUser) -> None:
    """Raise ForbiddenError if the actor cannot access this conversation."""
    # Прямой чат приватен — проверяем ДО привилегии менеджеров, иначе админ/менеджер
    # читали бы чужую личную переписку.
    if conv.kind == ConversationKind.DIRECT:
        if actor.id in (conv.client_id, conv.driver_id):
            return
        raise ForbiddenError("Это приватный чат")

    if actor.role in MANAGER_ROLES:
        return  # managers/admins see everything

    if conv.kind == ConversationKind.CLIENT_MANAGER:
        if actor.id == conv.client_id:
            return
        raise ForbiddenError("Это ваш диалог с менеджером")

    if conv.kind == ConversationKind.CLIENT_DRIVER_ORDER:
        if actor.id in (conv.client_id, conv.driver_id):
            return
        raise ForbiddenError("Вы не участник этого диалога")

    if conv.kind == ConversationKind.STAFF_GROUP:
        if actor.role == "driver" and conv.group_code in ("general", "drivers"):
            return
        raise ForbiddenError("У вас нет доступа к этому групповому чату")

    raise ForbiddenError("Доступ запрещён")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _auto_enroll(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Add actor to participants (for last_read_at tracking) if not already enrolled."""
    result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == actor.id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(ConversationParticipant(
            conversation_id=conv_id,
            user_id=actor.id,
            user_role=actor.role,
            last_read_at=datetime.now(timezone.utc),
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Ensure helpers (idempotent create-or-return)
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_client_manager(
    db: AsyncSession,
    client_id: uuid.UUID,
) -> Conversation:
    """Return existing client_manager conversation for this client, or create one."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.CLIENT_MANAGER,
            Conversation.client_id == client_id,
            Conversation.is_archived == False,  # noqa: E712
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        kind=ConversationKind.CLIENT_MANAGER,
        client_id=client_id,
        created_by_id=_SYSTEM_UUID,
        created_by_role="system",
    )
    db.add(conv)
    await db.flush()
    return conv


async def ensure_client_driver_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    client_id: uuid.UUID,
    driver_id: uuid.UUID,
    driver_name: str = "",
    order_number: str = "",
    redis: aioredis.Redis | None = None,
) -> Conversation:
    """Return existing client_driver_order conversation for this order, or create one.

    Called by order_service when a driver claims an order.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
            Conversation.order_id == order_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        # Update driver_id if it changed (shouldn't happen normally)
        if conv.driver_id != driver_id:
            conv.driver_id = driver_id
        return conv

    title = f"Заявка {order_number}" if order_number else None
    conv = Conversation(
        kind=ConversationKind.CLIENT_DRIVER_ORDER,
        client_id=client_id,
        driver_id=driver_id,
        order_id=order_id,
        title=title,
        created_by_id=_SYSTEM_UUID,
        created_by_role="system",
    )
    db.add(conv)
    await db.flush()

    # Post system message so participants see context
    if redis:
        system_text = (
            f"Водитель {driver_name} принял заявку {order_number}. "
            "Можете связаться напрямую."
        ) if driver_name else "Водитель принял заявку."
        await _post_system_message_raw(db, conv.id, system_text, redis)

    return conv


async def ensure_direct(
    db: AsyncSession,
    initiator_id: uuid.UUID,
    target_id: uuid.UUID,
) -> Conversation:
    """Вернуть существующий прямой чат между двумя пользователями или создать новый.

    Членство хранится в client_id (инициатор) и driver_id (собеседник); порядок
    при поиске не важен. Идемпотентно — повторный вызов вернёт тот же диалог.
    """
    if initiator_id == target_id:
        raise ForbiddenError("Нельзя начать чат с самим собой")

    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.DIRECT,
            Conversation.is_archived == False,  # noqa: E712
            or_(
                and_(Conversation.client_id == initiator_id, Conversation.driver_id == target_id),
                and_(Conversation.client_id == target_id, Conversation.driver_id == initiator_id),
            ),
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        kind=ConversationKind.DIRECT,
        client_id=initiator_id,
        driver_id=target_id,
        created_by_id=initiator_id,
        created_by_role="user",
    )
    db.add(conv)
    await db.flush()
    return conv


# ─────────────────────────────────────────────────────────────────────────────
# Staff group bootstrap (called at app startup)
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_staff_groups(db: AsyncSession) -> None:
    """Create the three staff_group conversations if they don't exist."""
    for code in STAFF_GROUPS:
        result = await db.execute(
            select(Conversation).where(
                Conversation.kind == ConversationKind.STAFF_GROUP,
                Conversation.group_code == code,
            )
        )
        if result.scalar_one_or_none():
            continue

        titles = {
            "general": "Общий чат",
            "drivers": "Чат водителей",
            "managers": "Чат менеджеров",
        }
        db.add(Conversation(
            kind=ConversationKind.STAFF_GROUP,
            group_code=code,
            title=titles.get(code, code),
            created_by_id=_SYSTEM_UUID,
            created_by_role="system",
        ))

    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def get_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .options(
            selectinload(Conversation.participants),
            selectinload(Conversation.messages),
            # Не отдаём soft-deleted сообщения: иначе удалённое сообщение всплывало
            # снова при переоткрытии диалога (в отличие от /messages, который их прячет).
            with_loader_criteria(Message, Message.is_archived == False),  # noqa: E712
        )
        .where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")

    _check_access(conv, actor)
    await _auto_enroll(db, conv_id, actor)
    await db.commit()
    await db.refresh(conv, ["participants"])

    # Обогащаем участников именем и телефоном (задача: телефоны видны в чате).
    # Для прямого чата дополнительно резолвим собеседника, даже если он ещё не
    # открывал диалог и потому отсутствует в таблице participants.
    wanted: set[uuid.UUID] = {p.user_id for p in conv.participants}
    if conv.kind == ConversationKind.DIRECT:
        if conv.client_id:
            wanted.add(conv.client_id)
        if conv.driver_id:
            wanted.add(conv.driver_id)
    contacts = await auth_client.get_contacts(list(wanted)) if wanted else {}

    for p in conv.participants:
        card = contacts.get(str(p.user_id))
        p.full_name = card.get("full_name") if card else None
        p.phone = card.get("phone") if card else None

    conv.peer_name = conv.peer_phone = None
    if conv.kind == ConversationKind.DIRECT:
        peer_id = conv.driver_id if conv.client_id == actor.id else conv.client_id
        card = contacts.get(str(peer_id)) if peer_id else None
        if card:
            conv.peer_name = card.get("full_name")
            conv.peer_phone = card.get("phone")

    return conv


async def list_conversations(
    db: AsyncSession,
    actor: TokenUser,
    order_id: uuid.UUID | None = None,  # kept for API compatibility, not used in new model
) -> list[dict]:
    """List conversations visible to this actor with unread counts and last message."""
    role = actor.role

    # ── Build visibility filter ───────────────────────────────────────────────
    if role == "client":
        # Auto-create client_manager if it doesn't exist yet
        cm = await ensure_client_manager(db, actor.id)
        await db.commit()

        visibility = or_(
            and_(
                Conversation.kind == ConversationKind.CLIENT_MANAGER,
                Conversation.client_id == actor.id,
            ),
            and_(
                Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
                Conversation.client_id == actor.id,
                Conversation.is_archived == False,  # noqa: E712
            ),
        )
    elif role == "driver":
        visibility = or_(
            and_(
                Conversation.kind == ConversationKind.STAFF_GROUP,
                Conversation.group_code.in_(["general", "drivers"]),
            ),
            and_(
                Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
                Conversation.driver_id == actor.id,
                Conversation.is_archived == False,  # noqa: E712
            ),
        )
    else:  # manager / admin
        visibility = or_(
            and_(
                Conversation.kind == ConversationKind.STAFF_GROUP,
                Conversation.group_code.in_(["general", "managers"]),
            ),
            Conversation.kind == ConversationKind.CLIENT_MANAGER,
            and_(
                Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
                Conversation.is_archived == False,  # noqa: E712
            ),
        )

    # Прямые чаты видны их двум участникам независимо от роли.
    direct_vis = and_(
        Conversation.kind == ConversationKind.DIRECT,
        or_(Conversation.client_id == actor.id, Conversation.driver_id == actor.id),
    )

    q = (
        select(Conversation)
        .where(Conversation.is_archived == False, or_(visibility, direct_vis))  # noqa: E712
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(q)
    conversations = result.scalars().all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]

    # ── Unread counts ─────────────────────────────────────────────────────────
    actor_part_alias = ConversationParticipant.__table__.alias("actor_part")
    unread_q = (
        select(
            Message.conversation_id,
            func.count(Message.id).label("unread"),
        )
        .join(
            actor_part_alias,
            and_(
                actor_part_alias.c.conversation_id == Message.conversation_id,
                actor_part_alias.c.user_id == actor.id,
            ),
            isouter=True,
        )
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.is_archived == False,  # noqa: E712
            Message.sender_id != actor.id,
            (actor_part_alias.c.last_read_at.is_(None))
            | (Message.created_at > actor_part_alias.c.last_read_at),
        )
        .group_by(Message.conversation_id)
    )
    unread_res = await db.execute(unread_q)
    unread_counts: dict[uuid.UUID, int] = {
        row.conversation_id: row.unread for row in unread_res
    }

    # ── Last message per conversation ─────────────────────────────────────────
    max_ts_subq = (
        select(
            Message.conversation_id.label("conv_id"),
            func.max(Message.created_at).label("max_ts"),
        )
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.is_archived == False,  # noqa: E712
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    last_msgs_result = await db.execute(
        select(Message).join(
            max_ts_subq,
            and_(
                Message.conversation_id == max_ts_subq.c.conv_id,
                Message.created_at == max_ts_subq.c.max_ts,
            ),
        ).where(Message.is_archived == False)  # noqa: E712
    )
    last_msgs: dict[uuid.UUID, Message] = {
        m.conversation_id: m for m in last_msgs_result.scalars().all()
    }

    # Для прямых чатов резолвим «собеседника» (имя + телефон), чтобы фронт показал
    # его в заголовке/списке. Один батч-запрос на все peer-id.
    peer_ids = [
        (c.driver_id if c.client_id == actor.id else c.client_id)
        for c in conversations
        if c.kind == ConversationKind.DIRECT
    ]
    contacts = await auth_client.get_contacts(peer_ids) if peer_ids else {}

    output = []
    for conv in conversations:
        last_msg = last_msgs.get(conv.id)
        peer_name = peer_phone = None
        if conv.kind == ConversationKind.DIRECT:
            peer_id = conv.driver_id if conv.client_id == actor.id else conv.client_id
            card = contacts.get(str(peer_id)) if peer_id else None
            if card:
                peer_name = card.get("full_name")
                peer_phone = card.get("phone")
        output.append({
            "id": conv.id,
            "kind": conv.kind,
            "title": conv.title,
            "client_id": conv.client_id,
            "driver_id": conv.driver_id,
            "order_id": conv.order_id,
            "group_code": conv.group_code,
            "created_by_id": conv.created_by_id,
            "created_by_role": conv.created_by_role,
            "unread_count": unread_counts.get(conv.id, 0),
            "last_message": MessageResponse.model_validate(last_msg) if last_msg else None,
            "updated_at": conv.updated_at,
            "peer_name": peer_name,
            "peer_phone": peer_phone,
        })

    return output


async def mark_read(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == actor.id,
        )
    )
    participant = result.scalar_one_or_none()
    if participant:
        participant.last_read_at = datetime.now(timezone.utc)
    else:
        # Auto-enroll and mark read simultaneously
        db.add(ConversationParticipant(
            conversation_id=conv_id,
            user_id=actor.id,
            user_role=actor.role,
            last_read_at=datetime.now(timezone.utc),
        ))
    await db.commit()


async def archive_conversation(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Archive a conversation — manager/admin only."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")
    if actor.role not in MANAGER_ROLES:
        raise ForbiddenError("Только менеджер или администратор может архивировать диалог")
    conv.is_archived = True
    await db.commit()


async def delete_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
    redis: aioredis.Redis,
) -> None:
    """Hard-delete — admin only."""
    if actor.role != "admin":
        raise ForbiddenError("Удалить диалог полностью может только администратор")
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.execute(
        delete(ConversationParticipant).where(ConversationParticipant.conversation_id == conv_id)
    )
    await db.delete(conv)
    await db.commit()
    try:
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "event": "conversation_deleted",
            "conversation_id": str(conv_id),
        }))
    except Exception:
        logger.exception("Failed to publish conversation_deleted event")


async def clear_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
    redis: aioredis.Redis,
) -> None:
    """Clear message history — admin only."""
    if actor.role != "admin":
        raise ForbiddenError("Очистить историю может только администратор")
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Диалог не найден")
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.commit()
    try:
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "event": "conversation_cleared",
            "conversation_id": str(conv_id),
        }))
    except Exception:
        logger.exception("Failed to publish conversation_cleared event")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _post_system_message_raw(
    db: AsyncSession,
    conv_id: uuid.UUID,
    text: str,
    redis: aioredis.Redis,
) -> None:
    """Post a system message without going through message_service (avoids circular import)."""
    from app.models.message import Message as _Message
    msg = _Message(
        conversation_id=conv_id,
        sender_id=_SYSTEM_UUID,
        sender_role="system",
        sender_name="Система",  # Message.sender_name NOT NULL — иначе INSERT падает 500
        text=text,
        msg_type="system",
    )
    db.add(msg)
    await db.flush()

    # Update conversation updated_at
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if conv:
        conv.updated_at = datetime.now(timezone.utc)

    try:
        # Плоский payload — как message_service.post_system_message и websocket.py.
        # Раньше слался вложенный {event, message}, который фронт (ws.onmessage ждёт
        # плоскую структуру) не мог отрисовать → битый пузырь до перезагрузки.
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "id": str(msg.id),
            "conversation_id": str(conv_id),
            "sender_id": str(_SYSTEM_UUID),
            "sender_role": "system",
            "sender_name": "Система",
            "msg_type": "system",
            "text": text,
            "metadata": None,
            "created_at": msg.created_at.isoformat() if hasattr(msg, "created_at") and msg.created_at else None,
        }))
    except Exception:
        logger.warning("Failed to publish system message event for conv %s", conv_id)
