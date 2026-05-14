import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import get_current_user, TokenUser
from app.schemas.conversation import (
    ConversationCreateRequest, ConversationResponse, ConversationListResponse
)
from app.schemas.message import MessageResponse, SendMessageRequest
from app.services import conversation_service, message_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreateRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    return await conversation_service.create_conversation(db, data, actor)


@router.get("", response_model=list[ConversationListResponse])
async def list_conversations(
    order_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    rows = await conversation_service.list_conversations(db, actor, order_id)
    return [ConversationListResponse(**r) for r in rows]


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
):
    """Hard-delete диалога вместе с сообщениями — только администратор."""
    await conversation_service.delete_conversation(db, conv_id, actor)


@router.post("/{conv_id}/clear", status_code=204)
async def clear_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Очистить историю сообщений — только администратор."""
    await conversation_service.clear_conversation(db, conv_id, actor)


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
):
    return await message_service.send_message(
        db, conv_id, data.text, actor,
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
