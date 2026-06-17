"""Fetch client context (type, credit flag, tariff, credit_limit) from auth_service.

Called once per order-create to determine allowed payment types and pricing.
If auth_service is unavailable, raises HTTP 503 — we never silently fall back
to defaults that could allow a forbidden payment type through.
"""
import uuid
import logging
from dataclasses import dataclass
from decimal import Decimal

import httpx
from fastapi import HTTPException

from app.config import get_settings

log = logging.getLogger(__name__)

AUTH_SERVICE_URL = get_settings().auth_service_url
INTERNAL_SECRET = get_settings().internal_api_secret


@dataclass
class ClientContext:
    user_id: uuid.UUID
    client_type: str          # "individual" | "company"
    credit_allowed: bool
    tariff_id: uuid.UUID | None   # None → use default tariff
    credit_limit: Decimal | None  # None → no credit limit configured
    fuel_coefficient: float = 1.0      # multiplier for fuel price
    delivery_coefficient: float = 1.0  # multiplier for delivery cost


_COEF_MIN = 0.0
_COEF_MAX = 10.0


def _clamp_coef(raw, label: str, client_id) -> float:
    """Зажать коэффициент в [0, 10]. Защита от отрицательной/абсурдной цены
    при порче данных или ошибке админ-правки. Дефолт 1.0."""
    try:
        v = float(raw) if raw is not None else 1.0
    except (TypeError, ValueError):
        v = 1.0
    if v < _COEF_MIN or v > _COEF_MAX:
        log.warning("client %s: %s_coefficient=%s out of [%.1f,%.1f] — clamped",
                    client_id, label, v, _COEF_MIN, _COEF_MAX)
        v = min(max(v, _COEF_MIN), _COEF_MAX)
    return v


async def get_user_organization_ids(user_id: uuid.UUID) -> list[uuid.UUID]:
    """ID организаций, где пользователь — активный участник (для видимости заявок).

    Fail-open: при недоступности auth возвращаем [] — клиент видит хотя бы свои
    заявки по client_id, а не падает весь список.
    """
    url = f"{AUTH_SERVICE_URL}/api/v1/internal/users/{user_id}/organization-ids"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers={"X-Internal-Secret": INTERNAL_SECRET})
        if resp.status_code == 200:
            return [uuid.UUID(x) for x in resp.json()]
        log.warning("organization-ids returned %s for %s", resp.status_code, user_id)
    except Exception as exc:
        log.warning("Failed to fetch organization-ids for %s: %s", user_id, exc)
    return []


async def get_client_context(
    client_id: uuid.UUID, organization_id: uuid.UUID | None = None
) -> ClientContext:
    """Fetch client/organization context from auth_service internal endpoint.

    Если передан organization_id — возвращается коммерческий контекст организации
    (auth проверяет членство клиента; 404 → клиент не участник). Иначе — профиль.
    """
    url = f"{AUTH_SERVICE_URL}/api/v1/internal/clients/{client_id}/context"
    params = {"organization_id": str(organization_id)} if organization_id else None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                params=params,
                headers={"X-Internal-Secret": INTERNAL_SECRET},
            )
        if resp.status_code == 404:
            detail = (
                "Организация не найдена или вы не её участник"
                if organization_id else "Профиль клиента не найден"
            )
            raise HTTPException(status_code=400, detail=detail)
        if resp.status_code != 200:
            log.error(
                "auth_service returned %s for client context %s: %s",
                resp.status_code, client_id, resp.text,
            )
            raise HTTPException(
                status_code=503,
                detail="Сервис авторизации временно недоступен. Попробуйте позже.",
            )
        data = resp.json()
        return ClientContext(
            user_id=uuid.UUID(data["user_id"]),
            client_type=data["client_type"],
            credit_allowed=data["credit_allowed"],
            tariff_id=uuid.UUID(data["tariff_id"]) if data.get("tariff_id") else None,
            credit_limit=Decimal(str(data["credit_limit"])) if data.get("credit_limit") is not None else None,
            fuel_coefficient=_clamp_coef(data.get("fuel_coefficient"), "fuel", client_id),
            delivery_coefficient=_clamp_coef(data.get("delivery_coefficient"), "delivery", client_id),
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Failed to fetch client context for %s: %s", client_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Сервис авторизации временно недоступен. Попробуйте позже.",
        )
