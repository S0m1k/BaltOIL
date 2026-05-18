import uuid
import json
import logging
from datetime import datetime, timezone

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError
from app.models.call import Call, CallParticipant, CallStatus
from app.services.livekit_service import generate_room_token, create_room

logger = logging.getLogger(__name__)


async def _fetch_conversation_participants(
    conv_id: uuid.UUID,
    actor_token: str,
) -> list[dict]:
    """Получить список участников диалога из chat_service.

    Возвращает [{"user_id": "...", "user_role": "..."}].
    Использует JWT актора — chat_service сам проверит доступ.
    """
    url = f"{settings.chat_service_url}/conversations/{conv_id}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {actor_token}"})
        if resp.status_code == 404:
            raise NotFoundError("Диалог не найден")
        if resp.status_code == 403:
            raise ForbiddenError("Нет доступа к диалогу")
        resp.raise_for_status()
        data = resp.json()
        return data.get("participants", [])


async def start_call(
    db: AsyncSession,
    redis: aioredis.Redis,
    conv_id: uuid.UUID,
    actor: TokenUser,
    actor_token: str,
) -> tuple[Call, str]:
    """Создать звонок и вернуть (Call, JWT для инициатора)."""
    participants = await _fetch_conversation_participants(conv_id, actor_token)
    if not participants:
        raise NotFoundError("В диалоге нет участников")

    # Проверка: актор должен быть в списке участников (либо staff)
    p_ids = {uuid.UUID(p["user_id"]) for p in participants}
    if actor.id not in p_ids and actor.role not in {"admin", "manager"}:
        raise ForbiddenError("Вы не участник этого диалога")

    # Не даём начинать новый звонок, если в этом диалоге уже идёт активный
    existing = await db.execute(
        select(Call).where(
            Call.conversation_id == conv_id,
            Call.status.in_([CallStatus.RINGING, CallStatus.ACTIVE]),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("В этом диалоге уже идёт звонок")

    # Имя комнаты: префикс + случайный hex для непредсказуемости
    room_name = f"conv-{conv_id.hex[:8]}-{uuid.uuid4().hex[:8]}"

    call = Call(
        conversation_id=conv_id,
        room_name=room_name,
        initiated_by_id=actor.id,
        initiated_by_name=actor.name,
        status=CallStatus.RINGING,
    )
    db.add(call)
    await db.flush()

    # Записать всех участников диалога как приглашённых в звонок
    for p in participants:
        user_id = uuid.UUID(p["user_id"])
        # Для инициатора сразу проставим joined_at — он подключается первым
        is_initiator = user_id == actor.id
        db.add(CallParticipant(
            call_id=call.id,
            user_id=user_id,
            user_name=actor.name if is_initiator else "",
            user_role=p.get("user_role", "unknown"),
            joined_at=datetime.now(timezone.utc) if is_initiator else None,
        ))

    # Создать комнату ПЕРЕД commit — если LiveKit недоступен, транзакция откатится
    # и в БД не останется звонка-призрака в статусе RINGING без реальной комнаты.
    await create_room(room_name)

    await db.commit()
    await db.refresh(call)

    # Сгенерировать токен для инициатора
    initiator_token = generate_room_token(
        user_id=str(actor.id),
        user_name=actor.name,
        room_name=room_name,
    )

    # Уведомить остальных участников через Redis → notification_service → SSE
    recipient_ids = [str(uid) for uid in p_ids if uid != actor.id]
    await redis.publish("events:calls", json.dumps({
        "event": "call_initiated",
        "call_id": str(call.id),
        "room_name": room_name,
        "conversation_id": str(conv_id),
        "initiated_by_id": str(actor.id),
        "initiated_by_name": actor.name,
        "participant_ids": recipient_ids,
    }))

    return call, initiator_token


async def issue_token_for_room(
    db: AsyncSession,
    room_name: str,
    actor: TokenUser,
) -> tuple[Call, str]:
    """Выдать токен участнику для входа в существующую комнату."""
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.participants))
        .where(Call.room_name == room_name)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise NotFoundError("Звонок не найден")
    if call.status == CallStatus.ENDED:
        raise ConflictError("Звонок уже завершён")

    # Проверка доступа — только приглашённые участники могут подключиться
    invited_ids = {p.user_id for p in call.participants}
    if actor.id not in invited_ids and actor.role not in {"admin", "manager"}:
        raise ForbiddenError("Вы не приглашены в этот звонок")

    # Обновить имя участника (на случай если оно изменилось) и пометить как подключившегося
    for p in call.participants:
        if p.user_id == actor.id:
            p.user_name = actor.name
            if p.joined_at is None:
                p.joined_at = datetime.now(timezone.utc)
            break

    # Перевод звонка в ACTIVE при первом ответе (если ещё RINGING)
    if call.status == CallStatus.RINGING and actor.id != call.initiated_by_id:
        call.status = CallStatus.ACTIVE
        call.answered_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(call)

    token = generate_room_token(
        user_id=str(actor.id),
        user_name=actor.name,
        room_name=room_name,
    )
    return call, token


async def end_call(
    db: AsyncSession,
    redis: aioredis.Redis,
    call_id: uuid.UUID,
    actor: TokenUser,
) -> Call:
    """Принудительно завершить звонок (нажата кнопка «Завершить»)."""
    result = await db.execute(
        select(Call).options(selectinload(Call.participants)).where(Call.id == call_id)
    )
    call = result.scalar_one_or_none()
    if not call:
        raise NotFoundError("Звонок не найден")

    # Проверка доступа — только участники звонка и staff могут его завершить
    invited_ids = {p.user_id for p in call.participants}
    if actor.id not in invited_ids and actor.role not in {"admin", "manager"}:
        raise ForbiddenError("Вы не участник этого звонка")

    if call.status == CallStatus.ENDED:
        return call

    participant_ids = [str(p.user_id) for p in call.participants]

    # Помечаем как ENDED. Если никто не ответил — MISSED.
    call.status = CallStatus.ENDED if call.answered_at else CallStatus.MISSED
    call.ended_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(call)

    # Сообщить всем — пусть закроют UI
    await redis.publish("events:calls", json.dumps({
        "event": "call_ended",
        "call_id": str(call.id),
        "room_name": call.room_name,
        "conversation_id": str(call.conversation_id),
        "status": call.status.value,
        "participant_ids": participant_ids,
    }))

    return call
