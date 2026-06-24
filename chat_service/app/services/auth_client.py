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


async def get_contact(user_id: uuid.UUID) -> dict | None:
    """Карточка одного пользователя ({full_name, role, phone, messenger_blocked,
    client_type}) или None при ошибке/отсутствии."""
    contacts = await get_contacts([user_id])
    return contacts.get(str(user_id))


async def get_organization_ids(user_id: uuid.UUID) -> list[str]:
    """ID организаций, в которых пользователь — активный участник.

    Используется для правила показа чата «Бухгалтерия» (доступен клиенту,
    у которого есть хотя бы одна организация). Fail-open: при ошибке — [].
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_BASE}/internal/users/{user_id}/organization-ids",
                headers=_HEADERS,
            )
        resp.raise_for_status()
        return [str(x) for x in resp.json()]
    except Exception:
        logger.exception("auth get_organization_ids failed")
        return []


async def is_messenger_blocked(redis, user_id: uuid.UUID) -> bool:
    """Заблокирован ли мессенджер у пользователя (правки 2026-06-11).

    Ответ кэшируется в Redis на 60 с, чтобы не дёргать auth_service на каждое
    сообщение. Fail-open: при недоступности auth_service не блокируем.
    """
    key = f"msgblock:{user_id}"
    try:
        cached = await redis.get(key)
        if cached is not None:
            val = cached.decode() if isinstance(cached, (bytes, bytearray)) else str(cached)
            return val == "1"
    except Exception:
        pass
    card = await get_contact(user_id)
    blocked = bool(card and card.get("messenger_blocked"))
    try:
        await redis.set(key, "1" if blocked else "0", ex=60)
    except Exception:
        pass
    return blocked


async def get_users_by_role(roles: list[str]) -> list[uuid.UUID]:
    """ID активных пользователей с указанными ролями (для состава staff-групп).

    Fail-open: при ошибке — [], вызывающая сторона должна мягко деградировать
    (показать пустой список участников), а не падать с 500.
    """
    if not roles:
        return []
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_BASE}/internal/users-by-role",
                params={"roles": ",".join(roles)},
                headers=_HEADERS,
            )
        resp.raise_for_status()
        return [uuid.UUID(x) for x in resp.json()]
    except Exception:
        logger.exception("auth get_users_by_role failed")
        return []


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
