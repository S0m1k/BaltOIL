import hashlib
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.conversation import Conversation, ConversationParticipant, ConversationType
from app.models.message import Message
from app.schemas.conversation import ConversationCreateRequest
from app.schemas.message import MessageResponse
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError


STAFF_ROLES = {"admin", "manager", "driver"}
MANAGER_ROLES = {"admin", "manager"}


def _participants_hash(user_ids: list[uuid.UUID]) -> str:
    """SHA-256 от отсортированных UUID участников — для upsert-дедупликации."""
    sorted_ids = sorted(str(u) for u in user_ids)
    return hashlib.sha256("|".join(sorted_ids).encode()).hexdigest()


async def create_conversation(
    db: AsyncSession,
    data: ConversationCreateRequest,
    actor: TokenUser,
) -> Conversation:
    # Клиенты могут создавать только client_support
    if actor.role == "client" and data.type != ConversationType.CLIENT_SUPPORT:
        raise ForbiddenError("Клиент может создавать только чаты поддержки")

    # Полный список участников (включая создателя)
    participant_ids: list[uuid.UUID] = [actor.id]
    for pid in data.participant_ids:
        if pid not in participant_ids:
            participant_ids.append(pid)

    p_hash = _participants_hash(participant_ids)

    # Upsert: если чат с таким составом уже есть — вернуть его
    existing = await db.execute(
        select(Conversation)
        .options(
            selectinload(Conversation.participants),
            selectinload(Conversation.messages),
        )
        .where(
            Conversation.participants_hash == p_hash,
            Conversation.is_archived == False,  # noqa: E712
        )
    )
    ex = existing.scalar_one_or_none()
    if ex:
        return ex

    conv = Conversation(
        type=data.type,
        title=data.title,
        participants_hash=p_hash,
        created_by_id=actor.id,
        created_by_role=actor.role,
    )
    db.add(conv)
    await db.flush()

    for pid in participant_ids:
        db.add(ConversationParticipant(
            conversation_id=conv.id,
            user_id=pid,
            user_role="unknown",
        ))

    await db.commit()

    result = await db.execute(
        select(Conversation)
        .options(
            selectinload(Conversation.participants),
            selectinload(Conversation.messages),
        )
        .where(Conversation.id == conv.id)
    )
    return result.scalar_one()


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
        )
        .where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")
    _check_access(conv, actor)
    return conv


async def list_conversations(
    db: AsyncSession,
    actor: TokenUser,
    order_id: uuid.UUID | None = None,
) -> list[dict]:
    """Список диалогов с количеством непрочитанных и последним сообщением."""
    q = select(Conversation).where(Conversation.is_archived == False)  # noqa: E712

    if actor.role not in MANAGER_ROLES:
        participant_subq = (
            select(ConversationParticipant.conversation_id)
            .where(ConversationParticipant.user_id == actor.id)
            .scalar_subquery()
        )
        q = q.where(Conversation.id.in_(participant_subq))

        if actor.role == "client":
            q = q.where(Conversation.type == ConversationType.CLIENT_SUPPORT)
        elif actor.role == "driver":
            q = q.where(Conversation.type == ConversationType.INTERNAL)

    q = q.order_by(Conversation.updated_at.desc())
    result = await db.execute(q)
    conversations = result.scalars().all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]

    # ── Запрос 1: все участники + last_read_at текущего актора за один SELECT ──
    parts_result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id.in_(conv_ids)
        )
    )
    all_parts = parts_result.scalars().all()

    # Индекс: conv_id → [participants], conv_id → actor's last_read_at
    parts_by_conv: dict[uuid.UUID, list[ConversationParticipant]] = {}
    actor_read_at: dict[uuid.UUID, datetime | None] = {}
    for p in all_parts:
        parts_by_conv.setdefault(p.conversation_id, []).append(p)
        if p.user_id == actor.id:
            actor_read_at[p.conversation_id] = p.last_read_at

    # ── Запрос 2: последнее сообщение на каждый диалог (MAX created_at + JOIN) ──
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

    # ── Запрос 3: непрочитанные — получаем (conv_id, created_at) от других,
    # фильтруем по last_read_at в Python (last_read_at различается по диалогу) ──
    unread_rows = await db.execute(
        select(
            Message.conversation_id,
            Message.id,
            Message.created_at,
        ).where(
            Message.conversation_id.in_(conv_ids),
            Message.is_archived == False,  # noqa: E712
            Message.sender_id != actor.id,
        )
    )
    # Group by conv, count only messages newer than actor's last_read_at
    unread_counts: dict[uuid.UUID, int] = {cid: 0 for cid in conv_ids}
    for row in unread_rows:
        cid = row.conversation_id
        last_read = actor_read_at.get(cid)
        if last_read is None or row.created_at > last_read:
            unread_counts[cid] = unread_counts.get(cid, 0) + 1

    output = []
    for conv in conversations:
        parts = parts_by_conv.get(conv.id, [])
        last_msg = last_msgs.get(conv.id)
        output.append({
            "id": conv.id,
            "type": conv.type,
            "title": conv.title,
            "created_by_id": conv.created_by_id,
            "created_by_role": conv.created_by_role,
            "participant_ids": [str(p.user_id) for p in parts],
            "unread_count": unread_counts.get(conv.id, 0),
            "last_message": MessageResponse.model_validate(last_msg) if last_msg else None,
            "updated_at": conv.updated_at,
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
        await db.commit()


async def archive_conversation(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Архивировать диалог — только менеджер/админ."""
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


async def delete_conversation(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Hard-delete диалога — только администратор."""
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


async def clear_conversation(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Очистить историю сообщений — только администратор."""
    if actor.role != "admin":
        raise ForbiddenError("Очистить историю может только администратор")
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Диалог не найден")
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.commit()


def _check_access(conv: Conversation, actor: TokenUser) -> None:
    if actor.role in MANAGER_ROLES:
        return
    participant_ids = {p.user_id for p in conv.participants}
    if actor.id not in participant_ids:
        raise ForbiddenError("Вы не участник этого диалога")
    if actor.role == "client" and conv.type != ConversationType.CLIENT_SUPPORT:
        raise ForbiddenError("Клиент может обращаться только в поддержку")
    if actor.role == "driver" and conv.type != ConversationType.INTERNAL:
        raise ForbiddenError("Водитель может использовать только внутренний чат")
