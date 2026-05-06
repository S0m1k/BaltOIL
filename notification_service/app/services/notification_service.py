import uuid
import json
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType
from app.schemas.notification import PublishRequest


async def create_notifications(
    db: AsyncSession,
    data: PublishRequest,
) -> list[Notification]:
    """Persist one Notification row per recipient and return them."""
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
