import asyncio
import logging
import time
import uuid
import json
from pathlib import Path

import httpx
import redis.asyncio as aioredis
from jinja2 import Environment, FileSystemLoader, TemplateNotFound
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.notification import Notification, NotificationType
from app.schemas.notification import PublishRequest
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

# Lazy Redis client — created on first use, shared across tasks.
_redis: aioredis.Redis | None = None

_WS_KEY_TTL = 300  # must match ws_manager._KEY_TTL

# Notification types for which we must check WS presence before emailing.
# For these types, skip email if recipient is currently online.
# CALL_MISSED исключён намеренно: событие теперь публикуется только из end_call,
# когда звонок реально пропущен (никто не ответил) → email шлём всегда,
# независимо от текущего присутствия получателя.
_ONLINE_GATED_TYPES = {NotificationType.CHAT_MESSAGE, NotificationType.CHAT_NEW}


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def _recipient_is_online(user_id: uuid.UUID) -> bool:
    """Return True if the recipient has an active WS session (ws:online key is fresh)."""
    try:
        r = _get_redis()
        val = await r.get(f"ws:online:{user_id}")
        if val is None:
            return False
        return (time.time() - int(val)) < _WS_KEY_TTL
    except Exception:
        logger.warning("Could not check ws:online for user %s", user_id, exc_info=True)
        # Fail-open: treat as online so we don't spam on Redis outage
        return True

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "email"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=False,
)

# Maps NotificationType → (template_name, email subject)
_EMAIL_TEMPLATES: dict[NotificationType, tuple[str, str]] = {
    NotificationType.ORDER_CREATED:  ("order_created.txt",  "Заявка создана"),
    NotificationType.ORDER_STATUS:   ("order_in_transit.txt", "Статус заявки изменён"),
    NotificationType.REPORT_READY:   ("document_ready.txt",  "Документ готов"),
    NotificationType.CHAT_MESSAGE:   ("chat_message.txt",    "Новое сообщение"),
    NotificationType.CHAT_NEW:       ("chat_message.txt",    "Новое сообщение"),
    NotificationType.CALL_MISSED:    ("call_missed.txt",     "Пропущенный звонок"),
}

# order_claimed / order_delivered are signalled via ORDER_STATUS in the current
# notification model; dedicated templates exist for future use when the event
# is published with those explicit types.

# Extra templates not yet wired to a NotificationType variant are kept for
# Deploy 4/5 when order status granularity is extended.


async def _fetch_user_email(user_id: uuid.UUID) -> str | None:
    """Ask auth_service for the best delivery email for a user.

    Returns None on any error or if the user has no email configured.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.auth_service_url}/internal/users/{user_id}/email-target",
                headers={"X-Internal-Secret": settings.internal_api_secret},
            )
            if resp.status_code == 200:
                return resp.json().get("email")
    except Exception:
        logger.warning("Could not fetch email for user %s", user_id, exc_info=True)
    return None


def _render_template(template_name: str, notification: Notification) -> str | None:
    """Render a Jinja2 text template with notification fields.

    Returns rendered string, or None if the template file is missing.
    """
    try:
        tmpl = _jinja_env.get_template(template_name)
    except TemplateNotFound:
        logger.warning("Email template not found: %s", template_name)
        return None

    # Provide all notification fields as template variables so any template
    # can reference them.  Unknown variables just render as empty string via
    # Jinja2 default behaviour (undefined=Undefined, which renders to "").
    #
    # title/body — единственный источник реальных данных: order_service/
    # delivery_service формируют их с уже подставленным номером заявки,
    # адресом, водителем и т.д. Раньше здесь были заглушки client_name/
    # driver_name/route/pickup_date/document_type/order_number — они ВСЕГДА
    # рендерились пустыми (order_number вдобавок был сырым UUID entity_id),
    # хотя нужные данные уже лежали в title/body. Шаблоны переведены на
    # title/body напрямую — см. order_created.txt/order_in_transit.txt/
    # document_ready.txt.
    ctx = {
        "title":        notification.title,
        "body":         notification.body,
        "entity_type":  notification.entity_type,
        "entity_id":    str(notification.entity_id) if notification.entity_id else "",
        "sender_name":  notification.title,
        "message_body": notification.body,
        "caller_name":  notification.title,
    }
    return tmpl.render(**ctx)


async def _schedule_email(notification: Notification) -> None:
    """Fire-and-forget: fetch email address, render template, send.

    For chat/call types, skips delivery when the recipient is currently online
    (ws:online key present and fresh) — they are already seeing the message live.
    """
    tmpl_info = _EMAIL_TEMPLATES.get(notification.type)
    if tmpl_info is None:
        return  # no email configured for this notification type

    # Online-gate: do not email chat/call notifications to active users
    if notification.type in _ONLINE_GATED_TYPES:
        if await _recipient_is_online(notification.user_id):
            logger.debug(
                "skip email for %s user_id=%s — recipient is online",
                notification.type.value,
                notification.user_id,
            )
            return

    template_name, subject = tmpl_info

    email_addr = await _fetch_user_email(notification.user_id)
    if not email_addr:
        return  # user has no email — skip silently

    body = _render_template(template_name, notification)
    if body is None:
        return

    await send_email(email_addr, subject, body)


async def create_notifications(
    db: AsyncSession,
    data: PublishRequest,
) -> list[Notification]:
    """Persist one Notification row per recipient and return them.

    Email delivery НЕ запускается здесь — иначе письмо могло уйти за уведомление,
    которое затем откатилось (commit упал / rollback). Письма ставит в очередь
    schedule_emails(), который вызывают ТОЛЬКО после успешного commit.
    """
    notifications = []
    for uid in data.user_ids:
        n = Notification(
            user_id=uid,
            type=data.type,
            title=data.title,
            body=data.body,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
        )
        db.add(n)
        notifications.append(n)
    await db.flush()
    for n in notifications:
        await db.refresh(n)
    return notifications


def schedule_emails(notifications: list[Notification]) -> None:
    """Запланировать отправку email для уже закоммиченных уведомлений.

    Вызывать ТОЛЬКО после db.commit() — гарантия, что письмо соответствует
    durable-persisted строке. Строим транзиентные копии полей, чтобы фоновая
    таска не обращалась к ORM-объекту после закрытия сессии (DetachedInstanceError).
    Вызывать пока сессия ещё открыта (атрибуты доступны для чтения).
    """
    for n in notifications:
        snapshot = Notification(
            user_id=n.user_id,
            type=n.type,
            title=n.title,
            body=n.body,
            entity_type=n.entity_type,
            entity_id=n.entity_id,
        )
        # _schedule_email never raises; any failure is logged inside.
        asyncio.create_task(_schedule_email(snapshot))


async def list_notifications(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 30,
    unread_only: bool = False,
) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        q = q.where(Notification.is_read == False)  # noqa: E712
    q = q.order_by(Notification.created_at.desc()).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def mark_read(db: AsyncSession, notif_id: uuid.UUID, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.id == notif_id, Notification.user_id == user_id)
        .values(is_read=True)
    )


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)  # noqa: E712
        .values(is_read=True)
    )


def notif_to_json(n: Notification) -> str:
    return json.dumps({
        "id":          str(n.id),
        "user_id":     str(n.user_id),
        "type":        n.type.value,
        "title":       n.title,
        "body":        n.body,
        "entity_type": n.entity_type,
        "entity_id":   str(n.entity_id) if n.entity_id else None,
        "is_read":     n.is_read,
        "created_at":  n.created_at.isoformat(),
    })
