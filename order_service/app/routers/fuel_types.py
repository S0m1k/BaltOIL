"""Роутер каталога топлива.

GET  /fuel-types                — любой авторизованный пользователь
POST /fuel-types                — только admin
PUT  /fuel-types/{code}         — только admin
DELETE /fuel-types/{code}       — только admin (мягкое удаление)
"""
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Query, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.schemas.fuel_type import FuelTypeInfo, FuelTypeCreate, FuelTypeUpdate
from app.services import fuel_type_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/fuel-types", tags=["fuel-types"])

AdminUser = Annotated[object, Depends(require_roles("admin"))]


@router.get("", response_model=list[FuelTypeInfo])
async def list_fuel_types(
    _: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    available_only: bool = Query(
        False,
        description="Если true — вернуть только виды топлива с остатком > 0 на складе",
    ),
):
    """Список активных видов топлива из каталога.

    При available_only=true дополнительно фильтрует по остаткам из delivery_service.
    Если delivery_service недоступен, фильтрация по остаткам пропускается (fail-open).
    """
    entries = await fuel_type_service.list_active(db)

    if available_only:
        in_stock = await fuel_type_service.fetch_in_stock_codes()
        if in_stock is not None:
            entries = [e for e in entries if e.code in in_stock]

    return entries


@router.post("", response_model=FuelTypeInfo, status_code=status.HTTP_201_CREATED)
async def create_fuel_type(
    data: FuelTypeCreate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Создать новый вид топлива (только admin)."""
    try:
        entry = await fuel_type_service.create_fuel_type(db, data)
        await db.commit()
        await db.refresh(entry)
        return entry
    except Exception as exc:
        from app.core.exceptions import ValidationError as VE
        if isinstance(exc, VE):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        raise


@router.put("/{code}", response_model=FuelTypeInfo)
async def update_fuel_type(
    code: str,
    data: FuelTypeUpdate,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Обновить запись каталога (только admin)."""
    entry = await fuel_type_service.update_fuel_type(db, code, data)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.delete("/{code}", response_model=FuelTypeInfo)
async def delete_fuel_type(
    code: str,
    _: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Деактивировать вид топлива (мягкое удаление, только admin)."""
    entry = await fuel_type_service.soft_delete(db, code)
    await db.commit()
    await db.refresh(entry)
    return entry
