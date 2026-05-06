import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, and_
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


def _is_staff(role: str) -> bool:
    return role in STAFF_ROLES


async def create_conversation(
    db: AsyncSession,
    data: ConversationCreateRequest,
    actor: TokenUser,
) -> Conversation:
    # Clients can only create CLIENT_SUPPORT conversations
    if actor.role == "client" and data.type != ConversationType.CLIENT_SUPPORT:
        raise ForbiddenError("Clients can only create client support conversations")

    conv = Conversation(
        type=data.type,
        order_id=data.order_id,
        title=data.title,
        created_by_id=actor.id,
        created_by_role=actor.role,
    )
    db.add(conv)
    await db.flush()  # get conv.id

    # Add creator as participant
    creator_participant = ConversationParticipant(
        conversation_id=conv.id,
        user_id=actor.id,
        user_role=actor.role,
    )
    db.add(creator_participant)

    # Add additional participants (staff only for internal, anyone for client_support)
    seen = {actor.id}
    for pid in data.participant_ids:
        if pid not in seen:
            p = ConversationParticipant(
                conversation_id=conv.id,
                user_id=pid,
                user_role="unknown",  # will be updated when they join via WS
            )
            db.add(p)
            seen.add(pid)

    await db.commit()
    await db.refresh(conv)

    # Eagerly load relations
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
        .where(Conversation.id == conv_id, Conversation.is_archived == False)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversation not found")

    _check_access(conv, actor)
    return conv


async def list_conversations(
    db: AsyncSession,
    actor: TokenUser,
    order_id: uuid.UUID | None = None,
) -> list[dict]:
    """Returns conversations with unread_count and last_message."""

    q = select(Conversation).where(Conversation.is_archived == False)

    # Managers/admins see ALL conversations; others see only theirs
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

    if order_id:
        q = q.where(Conversation.order_id == order_id)

    q = q.order_by(Conversation.updated_at.desc())
    result = await db.execute(q)
    conversations = result.scalars().all()

    # Build response with unread counts and last messages
    output = []
    for conv in conversations:
        # Get participant's last_read_at
        pr = await db.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conv.id,
                ConversationParticipant.user_id == actor.id,
            )
        )
        participant = pr.scalar_one_or_none()
        last_read_at = participant.last_read_at if participant else None

        # Count unread messages
        unread_q = select(func.count()).where(
            Message.conversation_id == conv.id,
            Message.is_archived == False,
            Message.sender_id != actor.id,
        )
        if last_read_at:
            unread_q = unread_q.where(Message.created_at > last_read_at)
        unread_count = (await db.execute(unread_q)).scalar() or 0

        # Get last message
        last_msg_result = await db.execute(
            select(Message)
            .where(Message.conversation_id == conv.id, Message.is_archived == False)
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        last_msg = last_msg_result.scalar_one_or_none()

        output.append({
            "id": conv.id,
            "type": conv.type,
            "order_id": conv.order_id,
            "title": conv.title,
            "created_by_id": conv.created_by_id,
            "created_by_role": conv.created_by_role,
            "unread_count": unread_count,
            "last_message": MessageResponse.model_validate(last_msg) if last_msg else None,
            "updated_at": conv.updated_at,
        })

    return output


async def mark_read(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
) -> None:
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


async def archive_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
) -> None:
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.is_archived == False)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Conversation not found")
    if actor.role not in MANAGER_ROLES:
        raise ForbiddenError("Only managers/admins can archive conversations")
    conv.is_archived = True
    await db.commit()


def _check_access(conv: Conversation, actor: TokenUser) -> None:
    """Raise ForbiddenError if actor cannot access this conversation."""
    if actor.role in MANAGER_ROLES:
        return  # managers/admins see everything

    # Check participation
    participant_ids = {p.user_id for p in conv.participants}
    if actor.id not in participant_ids:
        raise ForbiddenError("You are not a participant of this conversation")

    if actor.role == "client" and conv.type != ConversationType.CLIENT_SUPPORT:
        raise ForbiddenError("Clients can only access client support conversations")

    if actor.role == "driver" and conv.type != ConversationType.INTERNAL:
        raise ForbiddenError("Drivers can only access internal conversations")
