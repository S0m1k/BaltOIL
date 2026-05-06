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

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.notification import NotificationType
from app.schemas.notification import PublishRequest
from app.services.notification_service import create_notifications, notif_to_json

logger = logging.getLogger(__name__)

CHANNELS = ["events:orders", "events:chat"]


def _build_order_request(payload: dict) -> PublishRequest | None:
    event = payload.get("event")
    client_id = payload.get("client_id")
    driver_id = payload.get("driver_id")
    manager_id = payload.get("manager_id")
    order_id = payload.get("order_id")

    recipients: list[uuid.UUID] = []
    if event == "order_created":
        notif_type = NotificationType.ORDER_CREATED
        # Notify all managers/admins handled on publish side; here we notify client
        if client_id:
            recipients.append(uuid.UUID(client_id))
    elif event == "order_status":
        notif_type = NotificationType.ORDER_STATUS
        if client_id:
            recipients.append(uuid.UUID(client_id))
        if driver_id:
            recipients.append(uuid.UUID(driver_id))
    else:
        return None

    if not recipients:
        return None

    return PublishRequest(
        user_ids=recipients,
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


async def _handle(payload: dict, r: aioredis.Redis) -> None:
    event = payload.get("event", "")
    if event in ("order_created", "order_status"):
        req = _build_order_request(payload)
    elif event == "chat_message":
        req = _build_chat_request(payload)
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
