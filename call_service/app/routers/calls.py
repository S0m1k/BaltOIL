import uuid
import logging
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import redis.asyncio as aioredis

from app.config import settings
from app.database import get_db
from app.core.dependencies import TokenUser, get_current_user
from app.core.exceptions import AuthError, NotFoundError, ForbiddenError
from app.models.call import Call, CallStatus
from app.schemas.call import (
    StartCallRequest,
    TokenRequest,
    TokenResponse,
    CallResponse,
)
from app.services.call_service import start_call, issue_token_for_room, end_call
from app.services.livekit_service import delete_room

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/calls", tags=["calls"])


def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _extract_bearer(authorization: str) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Missing Bearer token")
    return authorization[7:]


@router.post("/start", response_model=TokenResponse, status_code=201)
async def start(
    body: StartCallRequest,
    request: Request,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Инициировать звонок в рамках диалога.

    Сервер:
      1. Получает список участников диалога из chat_service (с проверкой доступа).
      2. Создаёт запись Call со статусом RINGING.
      3. Создаёт комнату в LiveKit.
      4. Публикует событие call_initiated в Redis — notification_service разошлёт уведомления.
      5. Возвращает инициатору токен для немедленного подключения.
    """
    actor_token = _extract_bearer(request.headers.get("authorization", ""))
    redis = _get_redis()
    try:
        call, token = await start_call(
            db=db,
            redis=redis,
            conv_id=body.conversation_id,
            actor=actor,
            actor_token=actor_token,
        )
    finally:
        await redis.aclose()

    return TokenResponse(
        call_id=call.id,
        room_name=call.room_name,
        token=token,
        livekit_url=settings.livekit_public_url,
    )


@router.post("/token", response_model=TokenResponse)
async def get_token(
    body: TokenRequest,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Выдать токен для подключения к существующей комнате — используется при «Ответить»."""
    call, token = await issue_token_for_room(db, body.room_name, actor)
    return TokenResponse(
        call_id=call.id,
        room_name=call.room_name,
        token=token,
        livekit_url=settings.livekit_public_url,
    )


@router.post("/{call_id}/end", response_model=CallResponse)
async def end(
    call_id: uuid.UUID,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Принудительно завершить звонок (нажата «Положить трубку» / «Отклонить»)."""
    redis = _get_redis()
    try:
        call = await end_call(db, redis, call_id, actor)
    finally:
        await redis.aclose()

    # Принудительно удалить комнату в LiveKit — выкинет всех оставшихся
    try:
        await delete_room(call.room_name)
    except Exception:
        logger.exception("Failed to delete LiveKit room %s", call.room_name)

    # Подгрузить участников для ответа
    result = await db.execute(
        select(Call).options(selectinload(Call.participants)).where(Call.id == call.id)
    )
    call = result.scalar_one()
    return call


@router.get("/active", response_model=list[CallResponse])
async def active_calls(
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список активных звонков, в которые приглашён текущий пользователь."""
    from app.models.call import CallParticipant
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.participants))
        .join(CallParticipant, CallParticipant.call_id == Call.id)
        .where(
            CallParticipant.user_id == actor.id,
            Call.status.in_([CallStatus.RINGING, CallStatus.ACTIVE]),
        )
        .order_by(Call.started_at.desc())
    )
    return list(result.unique().scalars().all())


@router.get("/conv/{conv_id}/active", response_model=CallResponse | None)
async def active_call_for_conv(
    conv_id: uuid.UUID,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Вернуть активный/звонящий звонок для диалога, или null если его нет.

    Используется фронтендом когда /calls/start вернул 409, чтобы получить
    call_id для последующего завершения перед новым вызовом.
    """
    from app.models.call import CallParticipant
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.participants))
        .where(
            Call.conversation_id == conv_id,
            Call.status.in_([CallStatus.RINGING, CallStatus.ACTIVE]),
        )
        .limit(1)
    )
    call = result.scalar_one_or_none()
    if not call:
        return None
    # Access check: staff always passes, others must be a participant
    invited_ids = {p.user_id for p in call.participants}
    if actor.id not in invited_ids and actor.role not in {"admin", "manager"}:
        raise ForbiddenError("Нет доступа к звонку")
    return call


@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    call_id: uuid.UUID,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Call).options(selectinload(Call.participants)).where(Call.id == call_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise NotFoundError("Звонок не найден")
    invited_ids = {p.user_id for p in call.participants}
    if actor.id not in invited_ids and actor.role not in {"admin", "manager"}:
        raise ForbiddenError("Нет доступа к звонку")
    return call
