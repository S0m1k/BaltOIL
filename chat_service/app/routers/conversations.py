import uuid
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user, TokenUser
from app.core.redis_dep import get_redis
from app.core.exceptions import ForbiddenError
from app.schemas.conversation import (
    ConversationResponse, ConversationListResponse, EnsureClientManagerRequest,
)
from app.schemas.message import MessageResponse, SendMessageRequest
from app.services import conversation_service, message_service, auth_client

router = APIRouter(prefix="/conversations", tags=["conversations"])


class StartByPhoneRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)


@router.post("/start-by-phone", response_model=ConversationListResponse)
async def start_by_phone(
    body: StartByPhoneRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Начать (или открыть существующий) прямой чат с пользователем по номеру телефона.

    Доступно всем ролям. Возвращает диалог; идемпотентно при повторном вызове.
    """
    target = await auth_client.lookup_by_phone(body.phone)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь с таким номером не найден")
    target_id = uuid.UUID(target["id"])
    if target_id == actor.id:
        raise HTTPException(status_code=400, detail="Нельзя начать чат с самим собой")

    conv = await conversation_service.ensure_direct(db, actor.id, target_id)
    await db.commit()
    return ConversationListResponse(
        id=conv.id,
        kind=conv.kind,
        title=conv.title,
        client_id=conv.client_id,
        driver_id=conv.driver_id,
        order_id=conv.order_id,
        group_code=conv.group_code,
        created_by_id=conv.created_by_id,
        created_by_role=conv.created_by_role,
        unread_count=0,
        last_message=None,
        updated_at=conv.updated_at,
        peer_name=target.get("full_name"),
        peer_phone=target.get("phone"),
    )


@router.get("", response_model=list[ConversationListResponse])
async def list_conversations(
    order_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    rows = await conversation_service.list_conversations(db, actor, order_id)
    return [ConversationListResponse(**r) for r in rows]


@router.post("/ensure-client-manager", response_model=ConversationListResponse)
async def ensure_client_manager(
    body: EnsureClientManagerRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Ensure a client_manager conversation exists for the given client.

    Returns existing or newly created conversation. Staff-only endpoint used when
    a manager clicks the "Чат" button on a client card.
    """
    if actor.role not in ("manager", "admin"):
        raise ForbiddenError("Только менеджер или администратор")
    conv = await conversation_service.ensure_client_manager(db, body.client_id)
    await db.commit()
    return ConversationListResponse(
        id=conv.id,
        kind=conv.kind,
        title=conv.title,
        client_id=conv.client_id,
        driver_id=conv.driver_id,
        order_id=conv.order_id,
        group_code=conv.group_code,
        created_by_id=conv.created_by_id,
        created_by_role=conv.created_by_role,
        unread_count=0,
        last_message=None,
        updated_at=conv.updated_at,
    )


@router.get("/{conv_id}", response_model=ConversationResponse)
async def get_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    return await conversation_service.get_conversation(db, conv_id, actor)


@router.post("/{conv_id}/read", status_code=204)
async def mark_read(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    await conversation_service.mark_read(db, conv_id, actor)


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Hard-delete conversation and all messages — admin only."""
    await conversation_service.delete_conversation(db, conv_id, actor, redis=redis)


@router.post("/{conv_id}/clear", status_code=204)
async def clear_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Clear message history — admin only."""
    await conversation_service.clear_conversation(db, conv_id, actor, redis=redis)


# --- Messages within a conversation ---

@router.get("/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conv_id: uuid.UUID,
    limit: int = 50,
    before_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    return await message_service.get_messages(db, conv_id, actor, limit, before_id)


@router.post("/{conv_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    conv_id: uuid.UUID,
    data: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    return await message_service.send_message(
        db, conv_id, data.text, actor, redis,
        msg_type=data.msg_type,
        metadata=data.metadata,
    )


@router.delete("/{conv_id}/messages/{msg_id}", status_code=204)
async def delete_message(
    conv_id: uuid.UUID,
    msg_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    await message_service.delete_message(db, msg_id, actor)
