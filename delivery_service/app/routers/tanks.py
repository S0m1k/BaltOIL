"""Ёмкости хранения топлива (правки 2026-07-14).

GET    /inventory/tanks                     — список (водитель/менеджер/админ)
POST   /inventory/tanks                     — создать (админ)
PATCH  /inventory/tanks/{id}                — переименовать/сменить топливо/скрыть (админ)
POST   /inventory/tanks/{id}/adjust         — корректировка литров/счётчика (админ)
POST   /inventory/tanks/{id}/arrival        — приход в ёмкость (водитель+)
POST   /inventory/tanks/{id}/issue          — выдача по счётчику (водитель+)
POST   /inventory/tanks/transfer            — перелив между ёмкостями (водитель+)
GET    /inventory/tanks/transactions        — журнал операций (водитель+)
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser
from app.schemas.tank import (
    TankCreate, TankUpdate, TankAdjust, TankArrival, TankIssue, TankTransfer,
    TankResponse, TankTxResponse,
)
from app.services import tank_service

router = APIRouter(prefix="/inventory/tanks", tags=["tanks"])


@router.get("", response_model=list[TankResponse], summary="Список ёмкостей")
async def list_tanks(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(False),
):
    return await tank_service.list_tanks(db, current_user, include_inactive=include_inactive)


@router.get("/transactions", response_model=list[TankTxResponse],
            summary="Журнал операций по ёмкостям")
async def list_tank_transactions(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    tank_id: uuid.UUID | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
):
    return await tank_service.list_transactions(
        db, current_user, tank_id=tank_id, date_from=date_from, date_to=date_to, limit=limit,
    )


@router.post("", response_model=TankResponse, status_code=201, summary="Создать ёмкость (админ)")
async def create_tank(
    data: TankCreate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tank = await tank_service.create_tank(db, data, current_user)
    await db.commit()
    return tank


@router.patch("/{tank_id}", response_model=TankResponse,
              summary="Переименовать / сменить топливо / скрыть (админ)")
async def update_tank(
    tank_id: uuid.UUID,
    data: TankUpdate,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tank = await tank_service.update_tank(db, tank_id, data, current_user)
    await db.commit()
    return tank


@router.post("/transfer", response_model=list[TankResponse],
             summary="Перелив между ёмкостями (все роли склада)")
async def transfer(
    data: TankTransfer,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tanks = await tank_service.transfer(db, data, current_user)
    await db.commit()
    return tanks


@router.post("/{tank_id}/adjust", response_model=TankResponse,
             summary="Корректировка остатка/счётчика (админ)")
async def adjust_tank(
    tank_id: uuid.UUID,
    data: TankAdjust,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tank = await tank_service.adjust_tank(db, tank_id, data, current_user)
    await db.commit()
    return tank


@router.post("/{tank_id}/arrival", response_model=TankResponse,
             summary="Приход топлива в ёмкость (водитель+)")
async def record_arrival(
    tank_id: uuid.UUID,
    data: TankArrival,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tank = await tank_service.record_arrival(db, tank_id, data, current_user)
    await db.commit()
    return tank


@router.post("/{tank_id}/issue", response_model=TankTxResponse,
             summary="Выдача по заявке: новое показание счётчика (водитель+)")
async def record_issue(
    tank_id: uuid.UUID,
    data: TankIssue,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    tx = await tank_service.record_issue(db, tank_id, data, current_user)
    await db.commit()
    return tx
