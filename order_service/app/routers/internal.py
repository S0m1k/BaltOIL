"""Внутренние эндпоинты order_service — только для межсервисных запросов."""
import hmac
import logging
import uuid
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.schemas.fuel_type import FuelTypeInfo
from app.schemas.driver_report import DriverOrderInfo
from app.services import fuel_type_service
from app.services import driver_report_query

log = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Проверяет X-Internal-Secret. 401 если заголовок отсутствует, 403 если не совпадает."""
    _settings = get_settings()
    if x_internal_secret is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Secret header is required",
        )
    if not hmac.compare_digest(
        x_internal_secret.encode(), _settings.internal_api_secret.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal secret",
        )


InternalDep = Annotated[None, Depends(_verify_internal_secret)]


@router.get(
    "/fuel-types",
    response_model=list[FuelTypeInfo],
    summary="Каталог топлива для delivery_service",
)
async def internal_list_fuel_types(
    _: InternalDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Возвращает все активные записи каталога (код, label, is_winter, sort_order).

    Потребляется delivery_service при обновлении кэша меток топлива.
    """
    entries = await fuel_type_service.list_active(db)
    return entries


@router.get(
    "/driver-orders",
    response_model=list[DriverOrderInfo],
    summary="Доставленные водителем заявки за период для отчёта delivery_service",
)
async def internal_driver_delivered_orders(
    _: InternalDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    driver_id: uuid.UUID = Query(..., description="UUID водителя"),
    date_from: datetime = Query(..., description="Начало периода (ISO 8601)"),
    date_to: datetime = Query(..., description="Конец периода (ISO 8601)"),
):
    """Заявки со статусом «Доставлена», подтверждённые этим водителем в периоде.

    Период фильтруется по дате перехода в DELIVERED (история статусов).
    Авторизацию актора выполняет delivery_service до вызова этого эндпоинта.
    """
    return await driver_report_query.list_driver_delivered_orders(
        db, driver_id=driver_id, date_from=date_from, date_to=date_to,
    )
