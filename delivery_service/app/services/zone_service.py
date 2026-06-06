"""CRUD + resolve для зон доставки."""
import uuid
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.delivery_zone import DeliveryZone
from app.services.geo import point_in_polygon

log = logging.getLogger(__name__)


async def list_active(db: AsyncSession) -> list[DeliveryZone]:
    result = await db.execute(
        select(DeliveryZone)
        .where(DeliveryZone.is_active == True)  # noqa: E712
        .order_by(DeliveryZone.created_at)
    )
    return list(result.scalars().all())


async def list_all(db: AsyncSession) -> list[DeliveryZone]:
    result = await db.execute(
        select(DeliveryZone).order_by(DeliveryZone.created_at)
    )
    return list(result.scalars().all())


async def get(db: AsyncSession, zone_id: uuid.UUID) -> DeliveryZone | None:
    result = await db.execute(
        select(DeliveryZone).where(DeliveryZone.id == zone_id)
    )
    return result.scalar_one_or_none()


async def create(db: AsyncSession, data: dict) -> DeliveryZone:
    zone = DeliveryZone(
        name=data["name"],
        polygon=data["polygon"],
        cost_coefficient=Decimal(str(data.get("cost_coefficient", "1.0"))),
        is_active=data.get("is_active", True),
    )
    db.add(zone)
    await db.flush()
    return zone


async def update(db: AsyncSession, zone_id: uuid.UUID, data: dict) -> DeliveryZone | None:
    zone = await get(db, zone_id)
    if zone is None:
        return None
    if "name" in data and data["name"] is not None:
        zone.name = data["name"]
    if "polygon" in data and data["polygon"] is not None:
        zone.polygon = data["polygon"]
    if "cost_coefficient" in data and data["cost_coefficient"] is not None:
        zone.cost_coefficient = Decimal(str(data["cost_coefficient"]))
    if "is_active" in data and data["is_active"] is not None:
        zone.is_active = data["is_active"]
    await db.flush()
    return zone


async def soft_delete(db: AsyncSession, zone_id: uuid.UUID) -> DeliveryZone | None:
    """Деактивация зоны (мягкое удаление)."""
    zone = await get(db, zone_id)
    if zone is None:
        return None
    zone.is_active = False
    await db.flush()
    return zone


async def resolve(
    db: AsyncSession, lat: float, lon: float
) -> DeliveryZone | None:
    """Найти первую активную зону, в которую попадает точка (lat, lon)."""
    zones = await list_active(db)
    for zone in zones:
        try:
            if point_in_polygon(lat, lon, zone.polygon):
                return zone
        except Exception as exc:
            log.warning("zone %s polygon error: %s", zone.id, exc)
    return None
