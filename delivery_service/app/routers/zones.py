"""Роутер зон доставки.

GET  /zones                  — список активных зон (любой авторизованный пользователь)
POST /zones                  — создать зону (admin)
PUT  /zones/{id}             — обновить зону (admin)
DELETE /zones/{id}           — мягко удалить зону (admin)
POST /zones/resolve          — определить зону по координатам (любой авторизованный)
GET  /zones/suggest-address  — автодополнение адреса через DaData (любой авторизованный)
"""
import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import (
    CurrentUser,
    TokenUser,
    ROLE_ADMIN,
    require_roles,
)
from app.services import zone_service
from app.services.dadata_address import suggest_address

log = logging.getLogger(__name__)

router = APIRouter(prefix="/zones", tags=["zones"])

AdminDep = Annotated[TokenUser, Depends(require_roles(ROLE_ADMIN))]


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ZoneCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    polygon: list[list[float]] = Field(..., min_length=3)
    cost_coefficient: float = Field(1.0, ge=0)
    is_active: bool = True


class ZoneUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    polygon: list[list[float]] | None = Field(None, min_length=3)
    cost_coefficient: float | None = Field(None, ge=0)
    is_active: bool | None = None


class ZoneResponse(BaseModel):
    id: uuid.UUID
    name: str
    polygon: list[list[float]]
    cost_coefficient: float
    is_active: bool

    model_config = {"from_attributes": True}


class ResolveRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)


class ResolveResponse(BaseModel):
    zone_id: uuid.UUID | None = None
    name: str | None = None
    cost_coefficient: float | None = None


class AddressSuggestion(BaseModel):
    value: str
    lat: float | None
    lon: float | None


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[ZoneResponse])
async def list_zones(
    _: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Список активных зон для отображения на карте."""
    return await zone_service.list_active(db)


@router.post("", response_model=ZoneResponse, status_code=status.HTTP_201_CREATED)
async def create_zone(
    body: ZoneCreate,
    _: AdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await zone_service.create(db, body.model_dump())
    await db.commit()
    await db.refresh(zone)
    return zone


@router.put("/{zone_id}", response_model=ZoneResponse)
async def update_zone(
    zone_id: uuid.UUID,
    body: ZoneUpdate,
    _: AdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await zone_service.update(db, zone_id, body.model_dump(exclude_none=True))
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Зона не найдена")
    await db.commit()
    await db.refresh(zone)
    return zone


@router.delete("/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_zone(
    zone_id: uuid.UUID,
    _: AdminDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    zone = await zone_service.soft_delete(db, zone_id)
    if zone is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Зона не найдена")
    await db.commit()


@router.post("/resolve", response_model=ResolveResponse)
async def resolve_zone(
    body: ResolveRequest,
    _: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Определить зону по координатам. Если точка не в зоне → все поля null."""
    zone = await zone_service.resolve(db, body.lat, body.lon)
    if zone is None:
        return ResolveResponse()
    return ResolveResponse(
        zone_id=zone.id,
        name=zone.name,
        cost_coefficient=float(zone.cost_coefficient),
    )


@router.get("/suggest-address", response_model=list[AddressSuggestion])
async def suggest_address_endpoint(
    _: CurrentUser,
    q: str = Query(..., min_length=1, max_length=200, description="Строка адреса для автодополнения"),
):
    """Автодополнение адреса через DaData. Возвращает [] если токен не настроен."""
    suggestions = await suggest_address(q)
    return [
        AddressSuggestion(value=s["value"], lat=s["lat"], lon=s["lon"])
        for s in suggestions
    ]
