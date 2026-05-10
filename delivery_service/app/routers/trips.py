import uuid
from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.trip import TripStatus
from app.core.dependencies import CurrentUser, require_roles, ROLE_ADMIN, ROLE_MANAGER, ROLE_DRIVER
from app.schemas.trip import TripResponse, TripCreateRequest, TripStartRequest, TripCompleteRequest, TripAutoStartRequest
from app.services import trip_service

router = APIRouter(prefix="/trips", tags=["trips"])

# Только персонал (водитель, менеджер, администратор) — клиенты не допускаются
StaffOnly = Annotated[CurrentUser, Depends(require_roles(ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN))]


@router.get("", response_model=list[TripResponse])
async def list_trips(
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
    driver_id: uuid.UUID | None = Query(None),
    order_id: uuid.UUID | None = Query(None),
    status: TripStatus | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return await trip_service.list_trips(
        db, current_user,
        driver_id=driver_id, order_id=order_id, status=status,
        date_from=date_from, date_to=date_to,
        offset=offset, limit=limit,
    )


@router.post("/auto-start", response_model=TripResponse, status_code=201)
async def auto_start_trip(
    data: TripAutoStartRequest,
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Авто-создать и запустить рейс при переводе заявки в in_transit.
    Вызывается из order_service — синхронно проверяет и списывает топливо.
    Возвращает 422 если топлива недостаточно.
    """
    return await trip_service.auto_create_and_start(db, data, current_user)


@router.post("", response_model=TripResponse, status_code=201)
async def create_trip(
    data: TripCreateRequest,
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await trip_service.create_trip(db, data, current_user)


@router.get("/{trip_id}", response_model=TripResponse)
async def get_trip(
    trip_id: uuid.UUID,
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await trip_service.get_trip_by_id(db, trip_id, current_user)


@router.post("/{trip_id}/start", response_model=TripResponse)
async def start_trip(
    trip_id: uuid.UUID,
    data: TripStartRequest,
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель начинает рейс — статус PLANNED → IN_TRANSIT."""
    return await trip_service.start_trip(db, trip_id, data, current_user)


@router.post("/{trip_id}/complete", response_model=TripResponse)
async def complete_trip(
    trip_id: uuid.UUID,
    data: TripCompleteRequest,
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель фиксирует доставку — статус IN_TRANSIT → COMPLETED."""
    return await trip_service.complete_trip(db, trip_id, data, current_user)


@router.post("/{trip_id}/cancel", response_model=TripResponse)
async def cancel_trip(
    trip_id: uuid.UUID,
    current_user: StaffOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await trip_service.cancel_trip(db, trip_id, current_user)
