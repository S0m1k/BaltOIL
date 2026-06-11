"""Межсервисный вызов delivery_service для определения зоны доставки.

Fail-open: сетевая ошибка → None (не блокирует создание заявки).
"""
import logging
from decimal import Decimal

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


async def resolve_zone(lat: float, lon: float) -> dict | None:
    """Вызывает delivery_service /internal/zones/resolve.

    Возвращает {'zone_id': str, 'name': str, 'cost_coefficient': Decimal,
    'delivery_price': Decimal | None} или None если зона не найдена
    или сервис недоступен. delivery_price — фиксированная стоимость
    доставки по зоне в ₽ (правки 2026-06-11).
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{settings.delivery_service_url}/api/v1/internal/zones/resolve",
                json={"lat": lat, "lon": lon},
                headers={"X-Internal-Secret": settings.internal_api_secret},
            )
        if r.status_code != 200:
            log.warning("resolve_zone: delivery_service returned %s", r.status_code)
            return None
        data = r.json()
        if not data.get("zone_id"):
            return None
        return {
            "zone_id": data["zone_id"],
            "name": data["name"],
            "cost_coefficient": Decimal(str(data["cost_coefficient"])),
            "delivery_price": (
                Decimal(str(data["delivery_price"]))
                if data.get("delivery_price") is not None else None
            ),
        }
    except httpx.HTTPError as exc:
        log.warning("resolve_zone: HTTPError: %s", exc)
        return None
    except Exception as exc:
        log.warning("resolve_zone: unexpected error: %s", exc)
        return None
