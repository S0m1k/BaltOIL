"""Кто такой «водитель перевозок» (ТЗ Ирины: Бурнаев Сергей Викторович).

Жёсткого user_id в коде нет — это настройка:

1. ``TRANSPORT_DRIVER_ID`` в окружении order_service — прямой UUID водителя.
   Основной способ на проде: не зависит от переименований и однофамильцев.
2. Иначе водитель резолвится по фамилии ``TRANSPORT_DRIVER_NAME``
   (по умолчанию «Бурнаев») среди активных водителей auth_service.

Результат кешируется в памяти процесса: список водителей меняется редко, а
резолв дёргается на каждом создании перевозки. Кеш сбрасывается
``reset_cache()`` — им же пользуются тесты.
"""
from __future__ import annotations

import logging
import uuid

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

_cached_driver_id: uuid.UUID | None = None
_resolved: bool = False


def reset_cache() -> None:
    """Забыть найденного водителя (смена настройки, тесты)."""
    global _cached_driver_id, _resolved
    _cached_driver_id = None
    _resolved = False


def configured_driver_id() -> uuid.UUID | None:
    """UUID из TRANSPORT_DRIVER_ID, если он задан и корректен."""
    raw = (get_settings().transport_driver_id or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        log.error("TRANSPORT_DRIVER_ID=%r — не UUID, настройка игнорируется", raw)
        return None


def matches_configured_name(full_name: str | None) -> bool:
    """Похоже ли ФИО на настроенного водителя перевозок (без учёта регистра)."""
    needle = (get_settings().transport_driver_name or "").strip().casefold()
    if not needle:
        return False
    return needle in (full_name or "").casefold()


async def _fetch_driver_ids() -> list[str]:
    settings = get_settings()
    base = settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(
            f"{base}/api/v1/internal/users-by-role",
            params={"roles": "driver"},
            headers=headers,
        )
        r.raise_for_status()
        return [str(item) for item in r.json()]


async def _fetch_contacts(ids: list[str]) -> list[dict]:
    settings = get_settings()
    base = settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(
            f"{base}/api/v1/internal/users/contacts",
            params={"ids": ",".join(ids)},
            headers=headers,
        )
        r.raise_for_status()
        return list(r.json())


async def resolve_transport_driver_id() -> uuid.UUID | None:
    """Найти водителя перевозок. None — если не настроен и не нашёлся.

    Недоступность auth_service не считается фатальной: заявку на перевозку
    создаст менеджер и без назначенного водителя, а назначить сможет позже
    вручную. Иначе падение auth блокировало бы весь новый функционал.
    """
    global _cached_driver_id, _resolved

    explicit = configured_driver_id()
    if explicit is not None:
        return explicit

    if _resolved:
        return _cached_driver_id

    try:
        driver_ids = await _fetch_driver_ids()
        if driver_ids:
            for contact in await _fetch_contacts(driver_ids):
                if matches_configured_name(contact.get("full_name")):
                    _cached_driver_id = uuid.UUID(str(contact["id"]))
                    break
    except Exception as exc:
        log.warning("Не удалось определить водителя перевозок (не критично): %r", exc)
        return None

    _resolved = True
    if _cached_driver_id is None:
        log.warning(
            "Водитель перевозок не найден: нет активного водителя с фамилией %r "
            "и не задан TRANSPORT_DRIVER_ID",
            get_settings().transport_driver_name,
        )
    return _cached_driver_id


async def is_transport_driver(user_id: uuid.UUID) -> bool:
    """Является ли пользователь водителем перевозок."""
    resolved = await resolve_transport_driver_id()
    return resolved is not None and resolved == user_id
