"""
LiveKit webhook receiver.

LiveKit posts JSON events here (configured in livekit/config.yaml).
Events we handle:
  - participant_joined / participant_left — update Call & CallParticipant timestamps.
  - room_finished                          — mark Call as ENDED.

Auth: LiveKit signs the request with a JWT in the Authorization header,
signed using the same API secret.
"""
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import redis.asyncio as aioredis
from livekit.api.webhook import WebhookReceiver
from livekit.api.access_token import TokenVerifier

from app.config import settings
from app.database import get_db
from app.models.call import Call, CallParticipant, CallStatus

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhook", tags=["webhook"])

_verifier = TokenVerifier(settings.livekit_api_key, settings.livekit_api_secret)
_receiver = WebhookReceiver(_verifier)


def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@router.post("/livekit")
async def livekit_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    body = (await request.body()).decode("utf-8")
    auth_header = request.headers.get("authorization", "")

    try:
        event = _receiver.receive(body, auth_header)
    except Exception:
        logger.exception("Invalid LiveKit webhook signature")
        return {"ok": False, "reason": "invalid signature"}

    event_type = event.event
    room = event.room
    participant = event.participant

    if not room:
        return {"ok": True}

    # Найти Call по имени комнаты
    result = await db.execute(
        select(Call)
        .options(selectinload(Call.participants))
        .where(Call.room_name == room.name)
    )
    call = result.scalar_one_or_none()
    if not call:
        logger.warning("Webhook for unknown room: %s", room.name)
        return {"ok": True}

    now = datetime.now(timezone.utc)
    redis = _get_redis()

    try:
        if event_type == "participant_joined" and participant:
            # Перевод RINGING → ACTIVE при подключении первого "ответившего"
            if call.status == CallStatus.RINGING and str(participant.identity) != str(call.initiated_by_id):
                call.status = CallStatus.ACTIVE
                call.answered_at = now

            # Обновить joined_at участника
            for p in call.participants:
                if str(p.user_id) == str(participant.identity):
                    if p.joined_at is None:
                        p.joined_at = now
                    break

            await db.commit()

        elif event_type == "participant_left" and participant:
            for p in call.participants:
                if str(p.user_id) == str(participant.identity):
                    p.left_at = now
                    break
            await db.commit()

        elif event_type == "room_finished":
            if call.status != CallStatus.ENDED:
                call.status = CallStatus.ENDED if call.answered_at else CallStatus.MISSED
                call.ended_at = now
                await db.commit()
                participant_ids = [str(p.user_id) for p in call.participants]
                await redis.publish("events:calls", json.dumps({
                    "event": "call_ended",
                    "call_id": str(call.id),
                    "room_name": call.room_name,
                    "conversation_id": str(call.conversation_id),
                    "status": call.status.value,
                    "participant_ids": participant_ids,
                }))
    finally:
        await redis.aclose()

    return {"ok": True}
