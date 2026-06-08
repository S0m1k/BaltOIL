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
from app.services.dadata_address import suggest_address, suggest_address_bounded

log = logging.getLogger(__name__)

# Регион FIAS: Санкт-Петербург и Ленинградская область
SPB_REGION_FIAS = "c2deb16a-0330-4f05-821f-1d09c93331e6"
LO_REGION_FIAS = "6d1ebb35-70c6-4129-bd55-da3969658f5d"

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
    full_value: str | None = None
    fias: str | None = None
    kind: str | None = None


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
    level: str = Query("full", description="Уровень подсказки: full|city|street|house"),
    parent_fias: str | None = Query(None, description="FIAS родительского объекта (для street/house)"),
    parent_kind: str | None = Query(None, description="Тип родителя: city|settlement|street (для street)"),
):
    """Автодополнение адреса через DaData.

    level=full (по умолч.) — полный адрес, обратная совместимость.
    level=city  — город/нас.пункт в СПб + Ленобласти.
    level=street — улица внутри parent_fias (parent_kind обязателен).
    level=house  — дом внутри street parent_fias.
    Возвращает [] если токен не настроен или обязательные параметры отсутствуют.
    """
    if level == "full":
        suggestions = await suggest_address(q)
        return [
            AddressSuggestion(value=s["value"], lat=s["lat"], lon=s["lon"])
            for s in suggestions
        ]

    if level == "city":
        raw = await suggest_address_bounded(
            q,
            from_bound="city",
            to_bound="settlement",
            locations=[
                {"region_fias_id": SPB_REGION_FIAS},
                {"region_fias_id": LO_REGION_FIAS},
            ],
        )
        result = []
        for s in raw:
            fias = s.get("settlement_fias_id") or s.get("city_fias_id")
            kind = "settlement" if s.get("settlement_fias_id") else "city"
            result.append(AddressSuggestion(
                value=s["value"],
                full_value=s["full_value"],
                lat=s["lat"],
                lon=s["lon"],
                fias=fias,
                kind=kind,
            ))
        return result

    if level == "street":
        if not parent_fias or not parent_kind:
            return []
        raw = await suggest_address_bounded(
            q,
            from_bound="street",
            to_bound="street",
            locations=[{f"{parent_kind}_fias_id": parent_fias}],
        )
        result = []
        for s in raw:
            result.append(AddressSuggestion(
                value=s["value"],
                full_value=s["full_value"],
                lat=s["lat"],
                lon=s["lon"],
                fias=s.get("street_fias_id"),
                kind="street",
            ))
        return result

    if level == "house":
        if not parent_fias:
            return []
        raw = await suggest_address_bounded(
            q,
            from_bound="house",
            to_bound="house",
            locations=[{"street_fias_id": parent_fias}],
            restrict_value=False,
        )
        result = []
        for s in raw:
            result.append(AddressSuggestion(
                value=s["value"],
                full_value=s["full_value"],
                lat=s["lat"],
                lon=s["lon"],
                fias=s.get("fias_id"),
                kind="house",
            ))
        return result

    # Неизвестный level — деградация
    return []
