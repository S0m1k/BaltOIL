"""Internal endpoints — service-to-service only.

Not exposed through nginx; reachable only on the Docker internal network.
Auth: X-Internal-Secret header (HMAC-safe compare).
"""
import hmac
import uuid
from typing import Annotated
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.redis_dep import get_redis
from app.database import get_db
from app.schemas.message import MessageResponse
from app.schemas.conversation import ConversationListResponse
from app.services import message_service, conversation_service

router = APIRouter(prefix="/internal", tags=["internal"])


def _require_internal(x_internal_secret: str = Header(...)):
    secret = get_settings().internal_api_secret
    if not hmac.compare_digest(x_internal_secret, secret):
        raise HTTPException(status_code=403, detail="Bad internal secret")


class SystemMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    metadata: dict | None = None


class EnsureClientDriverRequest(BaseModel):
    order_id: uuid.UUID
    client_id: uuid.UUID
    driver_id: uuid.UUID
    driver_name: str = ""
    order_number: str = ""


@router.post(
    "/conversations/{conv_id}/system-message",
    response_model=MessageResponse,
    status_code=201,
    dependencies=[Depends(_require_internal)],
)
async def post_system_message(
    conv_id: uuid.UUID,
    body: SystemMessageRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    """Post a system message into a conversation (e.g., call events).

    sender_id = zero UUID, sender_role='system', msg_type='system'.
    Does not trigger push notifications — only published to WS.
    """
    return await message_service.post_system_message(
        db, conv_id, body.text, redis, metadata=body.metadata
    )


@router.post(
    "/conversations/ensure-client-driver",
    response_model=ConversationListResponse,
    status_code=200,
    dependencies=[Depends(_require_internal)],
)
async def ensure_client_driver(
    body: EnsureClientDriverRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    redis: Annotated[aioredis.Redis, Depends(get_redis)],
):
    """Ensure a client_driver_order conversation exists for this order.

    Called by order_service when a driver claims an order (claim_order).
    Idempotent — returns existing conversation if one already exists for the order.
    Молча создаёт диалог без системного сообщения (правки 2026-06-23) — клиент
    видит нового собеседника в списке, push-уведомление шлёт order_service отдельно.
    """
    conv = await conversation_service.ensure_client_driver_order(
        db,
        order_id=body.order_id,
        client_id=body.client_id,
        driver_id=body.driver_id,
        driver_name=body.driver_name,
        order_number=body.order_number,
        redis=redis,
    )
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
