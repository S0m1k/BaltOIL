"""Internal endpoints — service-to-service only.

Не выставляются через nginx; доступны только в Docker-сети.
Авторизация: header X-Internal-Secret == INTERNAL_API_SECRET (HMAC compare).
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
from app.services import message_service

router = APIRouter(prefix="/internal", tags=["internal"])


def _require_internal(x_internal_secret: str = Header(...)):
    secret = get_settings().internal_api_secret
    if not hmac.compare_digest(x_internal_secret, secret):
        raise HTTPException(status_code=403, detail="Bad internal secret")


class SystemMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    metadata: dict | None = None


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
    """Записать системное сообщение в диалог (например, события звонка).

    sender_id фиксированный UUID нулей, sender_role='system', msg_type='system'.
    Не триггерит push-уведомления — только мгновенно прилетает в WS.
    """
    return await message_service.post_system_message(
        db, conv_id, body.text, redis, metadata=body.metadata
    )
