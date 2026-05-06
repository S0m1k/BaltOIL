import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.trip import Trip, TripStatus
from app.models.vehicle import Vehicle
from app.core.dependencies import TokenUser, ROLE_ADMIN, ROLE_MANAGER, ROLE_DRIVER
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.schemas.trip import TripCreateRequest, TripStartRequest, TripCompleteRequest


async def get_trip_by_id(
    db: AsyncSession,
    trip_id: uuid.UUID,
    actor: TokenUser,
) -> Trip:
    trip = await _get_trip(db, trip_id)
    if actor.role == ROLE_DRIVER and trip.driver_id != actor.id:
        raise ForbiddenError()
    return trip


async def _get_trip(db: AsyncSession, trip_id: uuid.UUID) -> Trip:
    result = await db.execute(
        select(Trip).where(Trip.id == trip_id, Trip.is_archived == False)  # noqa: E712
    )
    t = result.scalar_one_or_none()
    if not t:
        raise NotFoundError("Рейс не найден")
    return t


def _assert_driver_owns(trip: Trip, actor: TokenUser) -> None:
    if actor.role == ROLE_DRIVER and trip.driver_id != actor.id:
        raise ForbiddenError("Это не ваш рейс")


async def list_trips(
    db: AsyncSession,
    actor: TokenUser,
    *,
    driver_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    status: TripStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Trip]:
    conditions = [Trip.is_archived == False]  # noqa: E712

    # Водитель видит только свои рейсы
    if actor.role == ROLE_DRIVER:
        conditions.append(Trip.driver_id == actor.id)
    elif driver_id:
        conditions.append(Trip.driver_id == driver_id)

    if order_id:
        conditions.append(Trip.order_id == order_id)
    if status:
        conditions.append(Trip.status == status)
    if date_from:
        conditions.append(Trip.created_at >= date_from)
    if date_to:
        conditions.append(Trip.created_at <= date_to)

    result = await db.execute(
        select(Trip)
        .where(and_(*conditions))
        .order_by(Trip.created_at.desc())
        .offset(offset).limit(limit)
    )
    return list(result.scalars().all())


async def create_trip(
    db: AsyncSession,
    data: TripCreateRequest,
    actor: TokenUser,
) -> Trip:
    if actor.role not in (ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Рейс создаёт водитель или менеджер")

    # Водитель создаёт рейс только на себя; менеджер/админ передаёт driver_id явно
    if actor.role == ROLE_DRIVER:
        driver_id = actor.id
    else:
        if not data.driver_id:
            raise ValidationError("Менеджер должен указать driver_id при создании рейса")
        driver_id = data.driver_id

    # Проверяем ТС
    v_result = await db.execute(
        select(Vehicle).where(Vehicle.id == data.vehicle_id, Vehicle.is_archived == False)  # noqa: E712
    )
    vehicle = v_result.scalar_one_or_none()
    if not vehicle:
        raise NotFoundError("Транспортное средство не найдено")
    if not vehicle.is_active:
        raise ValidationError("ТС неактивно")

    # Водитель может взять только закреплённую за ним машину (или свободную)
    if actor.role == ROLE_DRIVER:
        if vehicle.assigned_driver_id and vehicle.assigned_driver_id != actor.id:
            raise ForbiddenError("Это ТС закреплено за другим водителем")

    trip = Trip(
        order_id=data.order_id,
        driver_id=driver_id,
        vehicle_id=data.vehicle_id,
        volume_planned=data.volume_planned,
        delivery_address=data.delivery_address,
        odometer_start=data.odometer_start,
        driver_notes=data.driver_notes,
        status=TripStatus.PLANNED,
    )
    db.add(trip)
    return trip


async def start_trip(
    db: AsyncSession,
    trip_id: uuid.UUID,
    data: TripStartRequest,
    actor: TokenUser,
) -> Trip:
    trip = await _get_trip(db, trip_id)
    _assert_driver_owns(trip, actor)

    if trip.status != TripStatus.PLANNED:
        raise ValidationError(f"Нельзя начать рейс со статусом «{trip.status.value}»")

    trip.status = TripStatus.IN_TRANSIT
    trip.departed_at = datetime.now(timezone.utc)
    if data.odometer_start is not None:
        trip.odometer_start = data.odometer_start
    if data.driver_notes is not None:
        trip.driver_notes = data.driver_notes
    return trip


async def complete_trip(
    db: AsyncSession,
    trip_id: uuid.UUID,
    data: TripCompleteRequest,
    actor: TokenUser,
) -> Trip:
    trip = await _get_trip(db, trip_id)
    _assert_driver_owns(trip, actor)

    if trip.status != TripStatus.IN_TRANSIT:
        raise ValidationError(f"Нельзя завершить рейс со статусом «{trip.status.value}»")

    trip.status = TripStatus.COMPLETED
    trip.arrived_at = datetime.now(timezone.utc)
    trip.volume_actual = data.volume_actual
    if data.odometer_end is not None:
        trip.odometer_end = data.odometer_end
    if data.driver_notes is not None:
        trip.driver_notes = data.driver_notes
    return trip


async def cancel_trip(
    db: AsyncSession,
    trip_id: uuid.UUID,
    actor: TokenUser,
) -> Trip:
    trip = await _get_trip(db, trip_id)

    if actor.role == ROLE_DRIVER:
        _assert_driver_owns(trip, actor)
    elif actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError()

    if trip.status == TripStatus.COMPLETED:
        raise ValidationError("Нельзя отменить завершённый рейс")

    trip.status = TripStatus.CANCELLED
    return trip
