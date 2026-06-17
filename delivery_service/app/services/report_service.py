"""Отчёт водителя — учёт заявок, которые он доставил за период.

Данные берутся из order_service (internal API): заявки со статусом
«Доставлена», подтверждённые этим водителем. Здесь — только список и литраж,
без привязки к рейсам.
"""
import logging
import uuid
from datetime import datetime

import httpx

from app.config import get_settings
from app.core.dependencies import TokenUser, ROLE_DRIVER, ROLE_ADMIN, ROLE_MANAGER
from app.core.exceptions import ForbiddenError
from app.schemas.report import DriverReportResponse, DriverOrderItem

log = logging.getLogger(__name__)


async def driver_report(
    db,  # сохранён в сигнатуре для совместимости с роутером; БД не используется
    actor: TokenUser,
    *,
    driver_id: uuid.UUID,
    date_from: datetime,
    date_to: datetime,
) -> DriverReportResponse:
    # Водитель может получить только свой отчёт
    if actor.role == ROLE_DRIVER and actor.id != driver_id:
        raise ForbiddenError("Можно получить только собственный отчёт")
    if actor.role not in (ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError()

    raw = await _fetch_delivered_orders(driver_id, date_from, date_to)

    orders = [DriverOrderItem(**item) for item in raw]
    total_volume_delivered = sum(
        o.volume_delivered for o in orders if o.volume_delivered is not None
    )

    return DriverReportResponse(
        driver_id=driver_id,
        period_from=date_from,
        period_to=date_to,
        total_orders=len(orders),
        total_volume_delivered=total_volume_delivered,
        orders=orders,
    )


async def _fetch_delivered_orders(
    driver_id: uuid.UUID,
    date_from: datetime,
    date_to: datetime,
) -> list[dict]:
    """Получить доставленные заявки водителя из order_service internal API."""
    _settings = get_settings()
    params = {
        "driver_id": str(driver_id),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{_settings.order_service_url}/api/v1/internal/driver-orders",
            params=params,
            headers={"X-Internal-Secret": _settings.internal_api_secret},
        )
    r.raise_for_status()
    return r.json()
