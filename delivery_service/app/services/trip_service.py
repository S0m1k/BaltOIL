import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

import httpx
from jose import jwt as jose_jwt

from app.config import settings
from app.models.trip import Trip, TripStatus
from app.models.vehicle import Vehicle
from app.core.dependencies import TokenUser, ROLE_ADMIN, ROLE_MANAGER, ROLE_DRIVER
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.schemas.trip import TripCreateRequest, TripStartRequest, TripCompleteRequest, TripAutoStartRequest
from app.services import inventory_service
from app.models.fuel_transaction import FUEL_TYPE_LABELS

log = logging.getLogger(__name__)

ORDER_SERVICE_URL = "http://order_service:8002"


def _make_service_token(actor: TokenUser) -> str:
    """Короткоживущий JWT от имени актора для межсервисных запросов."""
    return jose_jwt.encode(
        {
            "sub": str(actor.id),
            "role": actor.role,
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


async def _update_order_status(order_id: uuid.UUID, actor: TokenUser, **kwargs) -> None:
    """Обновить статус заявки в order_service (fire-and-forget).
    kwargs передаются как поля тела запроса вместе с to_status.
    Ошибки логируются на уровне ERROR — не прерывают текущую операцию,
    но должны попасть в мониторинг, так как order может зависнуть в IN_TRANSIT.
    """
    try:
        token = _make_service_token(actor)
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{ORDER_SERVICE_URL}/api/v1/orders/{order_id}/transition",
                json=kwargs,
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code not in (200, 400, 422):
                log.error(
                    "_update_order_status: unexpected HTTP %s for order %s — order may be stuck. body=%s",
                    r.status_code, order_id, r.text[:300],
                )
    except Exception as exc:
        log.error(
            "_update_order_status failed for order %s — order may be stuck in current status: %s",
            order_id, exc,
        )


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


async def auto_create_and_start(
    db: AsyncSession,
    data: TripAutoStartRequest,
    actor: TokenUser,
) -> Trip:
    """Создать рейс и сразу запустить его (статус IN_TRANSIT), списав топливо.

    Вызывается из order_service при переводе заявки в статус in_transit.
    Если топлива недостаточно — поднимает ValidationError (→ HTTP 422),
    и order_service отменяет смену статуса заявки.
    Идемпотентно: если активный рейс уже существует — возвращает его.
    """
    # Идемпотентность — не создаём второй рейс для той же заявки
    existing = await db.execute(
        select(Trip).where(
            Trip.order_id == data.order_id,
            Trip.status.in_([TripStatus.PLANNED, TripStatus.IN_TRANSIT]),
            Trip.is_archived == False,  # noqa: E712
        )
    )
    ex = existing.scalar_one_or_none()
    if ex:
        return ex

    trip = Trip(
        order_id=data.order_id,
        driver_id=data.driver_id,
        vehicle_id=None,  # авто-рейс создаётся без ТС
        status=TripStatus.IN_TRANSIT,
        volume_planned=data.volume_planned,
        delivery_address=data.delivery_address or None,
        departed_at=datetime.now(timezone.utc),
        inv_fuel_type=data.inv_fuel_type,
        inv_order_number=data.inv_order_number,
        inv_client_id=data.inv_client_id,
        inv_client_name=data.inv_client_name,
        inv_driver_name=data.inv_driver_name,
    )
    db.add(trip)
    await db.flush()
    await db.refresh(trip)

    # Списать топливо (ValidationError если недостаточно — транзакция откатится)
    await inventory_service.record_departure_on_start(db, trip, actor)

    await db.flush()
    await db.refresh(trip)
    return trip


async def create_trip(
    db: AsyncSession,
    data: TripCreateRequest,
    actor: TokenUser,
) -> Trip:
    """Ручное создание рейса (для особых случаев — доступно менеджеру/администратору)."""
    if actor.role not in (ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Рейс создаёт водитель или менеджер")

    if actor.role == ROLE_DRIVER:
        driver_id = actor.id
    else:
        if not data.driver_id:
            raise ValidationError("Менеджер должен указать driver_id при создании рейса")
        driver_id = data.driver_id

    vehicle = None
    if data.vehicle_id:
        v_result = await db.execute(
            select(Vehicle).where(Vehicle.id == data.vehicle_id, Vehicle.is_archived == False)  # noqa: E712
        )
        vehicle = v_result.scalar_one_or_none()
        if not vehicle:
            raise NotFoundError("Транспортное средство не найдено")
        if not vehicle.is_active:
            raise ValidationError("ТС неактивно")
        if actor.role == ROLE_DRIVER:
            if vehicle.assigned_driver_id and vehicle.assigned_driver_id != actor.id:
                raise ForbiddenError("Это ТС закреплено за другим водителем")

    inv_fuel = data.inv_fuel_type
    if inv_fuel and inv_fuel not in FUEL_TYPE_LABELS:
        raise ValidationError(f"Неизвестный вид топлива для учёта: {inv_fuel!r}")

    trip = Trip(
        order_id=data.order_id,
        driver_id=driver_id,
        vehicle_id=data.vehicle_id,
        volume_planned=data.volume_planned,
        delivery_address=data.delivery_address or None,
        driver_notes=data.driver_notes,
        status=TripStatus.PLANNED,
        inv_fuel_type=inv_fuel,
        inv_order_number=data.inv_order_number,
        inv_client_id=data.inv_client_id,
        inv_client_name=data.inv_client_name,
        inv_driver_name=data.inv_driver_name,
    )
    db.add(trip)
    await db.flush()
    await db.refresh(trip)
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
    if data.driver_notes is not None:
        trip.driver_notes = data.driver_notes

    await inventory_service.record_departure_on_start(db, trip, actor)

    await db.flush()
    await db.refresh(trip)

    # Обновить статус заявки на in_transit
    if trip.order_id:
        await _update_order_status(
            trip.order_id, actor,
            to_status="in_transit",
            comment="Рейс начат",
        )

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
    if data.driver_notes is not None:
        trip.driver_notes = data.driver_notes

    # Скорректировать остаток: факт vs план
    await inventory_service.record_departure_adjustment(db, trip, actor)

    await db.flush()
    await db.refresh(trip)

    # Переводим заявку в delivered (водитель завершил доставку)
    if trip.order_id:
        await _update_order_status(
            trip.order_id, actor,
            to_status="delivered",
            volume_delivered=float(data.volume_actual),
            comment="Доставка подтверждена водителем",
        )

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

    prev_status = trip.status
    trip.status = TripStatus.CANCELLED

    if prev_status == TripStatus.IN_TRANSIT:
        await inventory_service.record_reversal_for_cancelled_trip(db, trip, actor)

    await db.flush()
    await db.refresh(trip)
    return trip
