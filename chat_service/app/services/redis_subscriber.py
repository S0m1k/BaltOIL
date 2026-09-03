"""Подписка chat_service на канал events:orders.

Обрабатывается единственное событие — `order_deleted` (полное удаление заявки
админом): диалог заявки (kind=client_driver_order) удаляется вместе с
сообщениями, участниками и вложениями на диске.

Сообщения и участники уходят по ON DELETE CASCADE, файлы вложений лежат в
{media_root}/chat/{conv_id}/ — каталог удаляем целиком после коммита.
"""
import asyncio
import json
import logging
import os
import shutil
import uuid

import redis.asyncio as aioredis
from sqlalchemy import delete, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.conversation import Conversation

log = logging.getLogger(__name__)

CHANNELS = ["events:orders"]


def _remove_attachments(conv_id: uuid.UUID) -> None:
    """Удалить каталог вложений диалога. Ошибки логируем, но не падаем."""
    dir_path = os.path.join(settings.media_root, "chat", str(conv_id))
    try:
        shutil.rmtree(dir_path, ignore_errors=False)
    except FileNotFoundError:
        pass
    except OSError:
        log.warning("Не удалось удалить вложения диалога %s", conv_id, exc_info=True)


async def handle_order_deleted(db, order_id: uuid.UUID) -> list[uuid.UUID]:
    """Удалить диалоги заявки. Возвращает id удалённых диалогов."""
    conv_ids = (
        await db.execute(select(Conversation.id).where(Conversation.order_id == order_id))
    ).scalars().all()
    if not conv_ids:
        return []

    # Сообщения и участники удаляются каскадом по FK (ondelete="CASCADE").
    await db.execute(delete(Conversation).where(Conversation.id.in_(conv_ids)))
    await db.commit()

    for conv_id in conv_ids:
        _remove_attachments(conv_id)

    log.warning(
        "action=order.hard_deleted.chat_cleanup order_id=%s conversations=%s",
        order_id, len(conv_ids),
    )
    return list(conv_ids)


async def _handle(payload: dict) -> None:
    if payload.get("event") != "order_deleted":
        return
    raw_id = payload.get("order_id")
    if not raw_id:
        return
    try:
        order_id = uuid.UUID(raw_id)
    except (ValueError, AttributeError, TypeError):
        log.warning("order_deleted с некорректным order_id: %r", raw_id)
        return

    async with AsyncSessionLocal() as db:
        try:
            await handle_order_deleted(db, order_id)
        except Exception:
            log.exception("Не удалось удалить чат удалённой заявки %s", order_id)
            await db.rollback()


async def order_events_subscriber_task() -> None:
    """Фоновая задача: слушает events:orders, переподключаясь при сбоях."""
    # warning, а не info: в chat_service нет basicConfig(level=INFO), и строка
    # старта подписчика — та самая, по которой DEPLOY_NOTES велят проверять деплой.
    log.warning("Chat Redis subscriber starting…")
    while True:
        try:
            r = aioredis.from_url(settings.redis_url, decode_responses=True)
            pubsub = r.pubsub()
            await pubsub.subscribe(*CHANNELS)
            log.warning("Subscribed to %s", CHANNELS)
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                try:
                    payload = json.loads(msg["data"])
                except json.JSONDecodeError:
                    continue
                asyncio.create_task(_handle(payload))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Redis subscriber crashed, reconnecting in 5 s…")
            await asyncio.sleep(5)
