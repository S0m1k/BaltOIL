import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.vehicle import Vehicle
from app.core.dependencies import TokenUser, ROLE_ADMIN, ROLE_MANAGER
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError
from app.schemas.vehicle import VehicleCreateRequest, VehicleUpdateRequest


def _staff(actor: TokenUser) -> None:
    if actor.role not in (ROLE_ADMIN, ROLE_MANAGER):
        raise ForbiddenError("Управление ТС доступно администратору и менеджеру")


async def list_vehicles(
    db: AsyncSession,
    actor: TokenUser,
    *,
    include_inactive: bool = False,
) -> list[Vehicle]:
    conditions = [Vehicle.is_archived == False]  # noqa: E712
    if not include_inactive:
        conditions.append(Vehicle.is_active == True)  # noqa: E712

    # Водитель видит только свою машину
    if actor.role == "driver":
        conditions.append(Vehicle.assigned_driver_id == actor.id)

    result = await db.execute(
        select(Vehicle).where(and_(*conditions)).order_by(Vehicle.plate_number)
    )
    return list(result.scalars().all())


async def get_vehicle(db: AsyncSession, vehicle_id: uuid.UUID) -> Vehicle:
    result = await db.execute(
        select(Vehicle).where(Vehicle.id == vehicle_id, Vehicle.is_archived == False)  # noqa: E712
    )
    v = result.scalar_one_or_none()
    if not v:
        raise NotFoundError("Транспортное средство не найдено")
    return v


async def create_vehicle(
    db: AsyncSession,
    data: VehicleCreateRequest,
    actor: TokenUser,
) -> Vehicle:
    _staff(actor)

    # Уникальность госномера
    exists = await db.execute(
        select(Vehicle).where(Vehicle.plate_number == data.plate_number)
    )
    if exists.scalar_one_or_none():
        raise ConflictError(f"ТС с номером {data.plate_number} уже существует")

    v = Vehicle(**data.model_dump())
    db.add(v)
    await db.flush()
    await db.refresh(v)
    return v


async def update_vehicle(
    db: AsyncSession,
    vehicle_id: uuid.UUID,
    data: VehicleUpdateRequest,
    actor: TokenUser,
) -> Vehicle:
    _staff(actor)
    v = await get_vehicle(db, vehicle_id)

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(v, field, value)
    return v


async def archive_vehicle(
    db: AsyncSession,
    vehicle_id: uuid.UUID,
    actor: TokenUser,
) -> None:
    _staff(actor)
    v = await get_vehicle(db, vehicle_id)
    v.is_archived = True
    v.archived_at = datetime.now(timezone.utc)
    v.is_active = False
