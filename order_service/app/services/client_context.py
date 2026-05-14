"""Fetch client context (type, credit flag, tariff) from auth_service.

Called once per order-create to determine allowed payment types and pricing.
If auth_service is unavailable, raises HTTP 503 — we never silently fall back
to defaults that could allow a forbidden payment type through.
"""
import uuid
import logging
from dataclasses import dataclass

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


async def get_client_context(client_id: uuid.UUID) -> ClientContext:
    """Fetch client profile context from auth_service internal endpoint."""
    url = f"{AUTH_SERVICE_URL}/api/v1/internal/clients/{client_id}/context"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                url,
                headers={"X-Internal-Secret": INTERNAL_SECRET},
            )
        if resp.status_code == 404:
            raise HTTPException(status_code=400, detail="Профиль клиента не найден")
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
        )
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Failed to fetch client context for %s: %s", client_id, exc)
        raise HTTPException(
            status_code=503,
            detail="Сервис авторизации временно недоступен. Попробуйте позже.",
        )
