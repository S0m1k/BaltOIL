"""Тонкий клиент к auth_service для нужд чата.

- lookup_by_phone — найти пользователя по номеру («начать чат по номеру»).
- get_contacts    — батч-резолв id → {full_name, role, phone} для показа
                    телефонов участников диалога.

auth_service_url в конфиге уже содержит суффикс /api/v1, поэтому добавляем
только /internal/...
"""
import logging
import uuid

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_BASE = settings.auth_service_url.rstrip("/")
_HEADERS = {"X-Internal-Secret": settings.internal_api_secret}


async def lookup_by_phone(phone: str) -> dict | None:
    """Вернуть {id, full_name, role, phone} или None, если пользователь не найден."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_BASE}/internal/users/by-phone",
                params={"phone": phone},
                headers=_HEADERS,
            )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("auth lookup_by_phone failed")
        return None


async def get_contacts(ids: list[uuid.UUID]) -> dict[str, dict]:
    """Батч-резолв id → карточка. Возвращает {str(id): {full_name, role, phone}}.

    При ошибке возвращает пустой словарь — вызывающая сторона деградирует мягко
    (покажет id вместо имени), но не падает.
    """
    unique = {str(i) for i in ids if i}
    if not unique:
        return {}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_BASE}/internal/users/contacts",
                params={"ids": ",".join(unique)},
                headers=_HEADERS,
            )
        resp.raise_for_status()
        return {c["id"]: c for c in resp.json()}
    except Exception:
        logger.exception("auth get_contacts failed")
        return {}
