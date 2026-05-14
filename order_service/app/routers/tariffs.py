import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.schemas.tariff import (
    TariffCreateRequest, TariffUpdateRequest, TariffResponse,
    ClientPaymentOptionsResponse,
)
from app.services import tariff_service
from app.services.client_context import get_client_context
from app.services.payment_type_rules import _RULES
from app.models.order import PaymentType

router = APIRouter(prefix="/tariffs", tags=["tariffs"])

StaffOnly = Annotated[object, Depends(require_roles("manager", "admin"))]


@router.get("", response_model=list[TariffResponse])
async def list_tariffs(
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_archived: bool = Query(False),
):
    return await tariff_service.list_tariffs(db, actor, include_archived=include_archived)


@router.get("/default", response_model=TariffResponse)
async def get_default_tariff(
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tariff_service.get_default_tariff(db, actor)


@router.get("/{tariff_id}", response_model=TariffResponse)
async def get_tariff(
    tariff_id: uuid.UUID,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tariff_service.get_tariff_by_id(db, tariff_id, actor)


@router.post("", response_model=TariffResponse, status_code=201)
async def create_tariff(
    data: TariffCreateRequest,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tariff_service.create_tariff(
        db, actor,
        name=data.name,
        description=data.description,
        fuel_prices=[fp.model_dump() for fp in data.fuel_prices],
        volume_tiers=[t.model_dump() for t in data.volume_tiers],
    )


@router.put("/{tariff_id}", response_model=TariffResponse)
async def update_tariff(
    tariff_id: uuid.UUID,
    data: TariffUpdateRequest,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tariff_service.update_tariff(
        db, tariff_id, actor,
        name=data.name,
        description=data.description,
        fuel_prices=[fp.model_dump() for fp in data.fuel_prices],
        volume_tiers=[t.model_dump() for t in data.volume_tiers],
    )


@router.post("/{tariff_id}/set-default", response_model=TariffResponse)
async def set_default(
    tariff_id: uuid.UUID,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tariff_service.set_default_tariff(db, tariff_id, actor)


@router.post("/{tariff_id}/archive", response_model=TariffResponse)
async def archive_tariff(
    tariff_id: uuid.UUID,
    actor: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await tariff_service.archive_tariff(db, tariff_id, actor)


@router.get("/clients/{client_id}/payment-options", response_model=ClientPaymentOptionsResponse)
async def get_client_payment_options(
    client_id: uuid.UUID,
    actor: CurrentUser,
    _staff: StaffOnly,
):
    """Return available payment types for this client given actor's role.

    Used by the UI to render dynamic payment radio buttons when manager
    creates an order on behalf of a client.
    """
    ctx = await get_client_context(client_id)

    available = []
    for pt in PaymentType:
        allowed_types, staff_only, requires_credit = _RULES[pt]
        if staff_only and actor.role == "client":
            continue
        if ctx.client_type not in allowed_types:
            continue
        if requires_credit and not ctx.credit_allowed:
            continue
        available.append(pt.value)

    return ClientPaymentOptionsResponse(
        client_id=client_id,
        client_type=ctx.client_type,
        available_payment_types=available,
    )
