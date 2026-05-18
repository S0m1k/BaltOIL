"""
Background task that listens on shared Redis channels published by other services
and creates Notification rows + forwards to per-user SSE channels.

Channel protocol
────────────────
events:orders  – order_service publishes JSON on create / status change
events:chat    – chat_service publishes JSON on every new message

Payload shapes
──────────────
order event:
  { "event": "order_created"|"order_status",
    "order_id": "...", "client_id": "...",
    "driver_id": "...|null", "manager_id": "...|null",
    "status": "...", "title": "...", "body": "..." }

chat event:
  { "event": "chat_message",
    "conv_id": "...", "sender_id": "...", "sender_name": "...",
    "body": "...",
    "participant_ids": ["...", "..."] }
"""

import asyncio
import json
import logging
import uuid
import redis.asyncio as aioredis
import httpx

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.notification import NotificationType
from app.schemas.notification import PublishRequest
from app.services.notification_service import create_notifications, notif_to_json

logger = logging.getLogger(__name__)

CHANNELS = ["events:orders", "events:chat", "events:calls"]


async def _fetch_staff_ids() -> list[uuid.UUID]:
    """Get all active manager + admin user IDs from auth_service."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.auth_service_url}/internal/users-by-role",
                params={"roles": "manager,admin"},
                headers={"X-Internal-Secret": settings.internal_api_secret},
            )
            resp.raise_for_status()
            return [uuid.UUID(uid) for uid in resp.json()]
    except Exception:
        logger.warning("Could not fetch staff IDs from auth_service", exc_info=True)
        return []


async def _build_order_request(payload: dict) -> PublishRequest | None:
    event = payload.get("event")
    client_id = payload.get("client_id")
    driver_id = payload.get("driver_id")
    order_id = payload.get("order_id")

    recipients: list[uuid.UUID] = []
    if event == "order_created":
        notif_type = NotificationType.ORDER_CREATED
        # Notify client who placed the order
        if client_id:
            recipients.append(uuid.UUID(client_id))
        # Notify all managers and admins
        staff_ids = await _fetch_staff_ids()
        recipients.extend(staff_ids)
    elif event == "order_status":
        notif_type = NotificationType.ORDER_STATUS
        if client_id:
            recipients.append(uuid.UUID(client_id))
        if driver_id:
            recipients.append(uuid.UUID(driver_id))
    else:
        return None

    # Deduplicate
    seen: set[uuid.UUID] = set()
    unique: list[uuid.UUID] = []
    for uid in recipients:
        if uid not in seen:
            seen.add(uid)
            unique.append(uid)

    if not unique:
        return None

    return PublishRequest(
        user_ids=unique,
        type=notif_type,
        title=payload.get("title", "Order update"),
        body=payload.get("body", ""),
        entity_type="order",
        entity_id=uuid.UUID(order_id) if order_id else None,
    )


def _build_chat_request(payload: dict) -> PublishRequest | None:
    participant_ids = payload.get("participant_ids", [])
    sender_id = payload.get("sender_id")
    conv_id = payload.get("conv_id")
    sender_name = payload.get("sender_name", "Someone")
    body = payload.get("body", "")

    # Notify everyone except the sender
    recipients = [
        uuid.UUID(pid) for pid in participant_ids
        if pid != sender_id
    ]
    if not recipients:
        return None

    return PublishRequest(
        user_ids=recipients,
        type=NotificationType.CHAT_MESSAGE,
        title=f"New message from {sender_name}",
        body=body[:120],
        entity_type="conversation",
        entity_id=uuid.UUID(conv_id) if conv_id else None,
    )


async def _build_call_request(payload: dict) -> PublishRequest | None:
    event = payload.get("event")
    call_id = payload.get("call_id")
    initiator_name = payload.get("initiated_by_name", "Someone")
    initiator_id = payload.get("initiated_by_id")
    participant_ids = payload.get("participant_ids", [])

    if event == "call_initiated":
        recipients = [uuid.UUID(pid) for pid in participant_ids]
        # If no one to notify (e.g. no staff has ever joined the conversation),
        # fall back to all managers/admins so the call isn't silently dropped.
        if not recipients:
            recipients = await _fetch_staff_ids()
            # Remove the initiator so they don't ring themselves
            if initiator_id:
                initiator_uuid = uuid.UUID(initiator_id)
                recipients = [r for r in recipients if r != initiator_uuid]
        if not recipients:
            return None
        return PublishRequest(
            user_ids=recipients,
            type=NotificationType.CALL_INITIATED,
            title="Входящий звонок",
            body=f"{initiator_name} звонит вам",
            entity_type="call",
            entity_id=uuid.UUID(call_id) if call_id else None,
        )
    # call_ended/missed — мы рассылаем через прямую публикацию в notifs:{uid}
    # без создания строки в БД (это просто сигнал «закрой UI»).
    return None


async def _handle(payload: dict, r: aioredis.Redis) -> None:
    event = payload.get("event", "")
    if event in ("order_created", "order_status"):
        req = await _build_order_request(payload)
    elif event == "chat_message":
        req = _build_chat_request(payload)
    elif event == "call_initiated":
        req = await _build_call_request(payload)
    elif event == "call_ended":
        # Сигнальное событие — раздаём только по personal-каналам без записи в БД.
        # Фронтенд закроет диалог входящего звонка / активный звонок.
        signal = json.dumps({
            "type": "CALL_ENDED",
            "call_id": payload.get("call_id"),
            "room_name": payload.get("room_name"),
            "conversation_id": payload.get("conversation_id"),
            "status": payload.get("status"),
        })
        for pid in payload.get("participant_ids", []):
            try:
                await r.publish(f"notifs:{pid}", signal)
            except Exception:
                logger.exception("Failed to broadcast call_ended to %s", pid)
        return
    else:
        return

    if req is None:
        return

    async with AsyncSessionLocal() as db:
        try:
            notifications = await create_notifications(db, req)
            await db.commit()
            for n in notifications:
                channel = f"notifs:{n.user_id}"
                # Для звонков добавим room_name в SSE-пейлоад, чтобы фронт сразу мог подключиться
                if event == "call_initiated":
                    enriched = json.loads(notif_to_json(n))
                    enriched["room_name"] = payload.get("room_name")
                    enriched["initiated_by_name"] = payload.get("initiated_by_name")
                    await r.publish(channel, json.dumps(enriched))
                else:
                    await r.publish(channel, notif_to_json(n))
        except Exception:
            logger.exception("Failed to persist notification for event %s", event)
            await db.rollback()


async def redis_subscriber_task() -> None:
    logger.info("Notification Redis subscriber starting…")
    while True:
        try:
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(*CHANNELS)
            logger.info("Subscribed to %s", CHANNELS)
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    payload = json.loads(msg["data"])
                except json.JSONDecodeError:
                    continue
                asyncio.create_task(_handle(payload, r))
        except Exception:
            logger.exception("Redis subscriber crashed, reconnecting in 5 s…")
            await asyncio.sleep(5)
