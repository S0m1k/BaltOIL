"""Кэш каталога топлива из order_service.

Хранит {code: label} TTL-кэш (300 с). При недоступности сервиса возвращает
последний известный кэш или хардкод-фолбэк из fuel_transaction.py.
"""
import logging
import time

import httpx

from app.config import get_settings
from app.models.fuel_transaction import FUEL_TYPE_LABELS as _FALLBACK_LABELS

log = logging.getLogger(__name__)

_CACHE_TTL = 300  # секунды

# Состояние кэша — module-level (один экземпляр на процесс)
_cache: dict[str, str] = dict(_FALLBACK_LABELS)   # seed из хардкод-фолбэка
_cache_ts: float = 0.0                             # unix timestamp последнего обновления


async def get_fuel_labels() -> dict[str, str]:
    """Вернуть актуальный {code: label}.

    Кэш обновляется каждые _CACHE_TTL секунд из order_service internal API.
    При любой ошибке возвращает последний успешный кэш (или хардкод-фолбэк).
    """
    global _cache, _cache_ts

    now = time.monotonic()
    if now - _cache_ts < _CACHE_TTL:
        return dict(_cache)

    try:
        _settings = get_settings()
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{_settings.order_service_url}/api/v1/internal/fuel-types",
                headers={"X-Internal-Secret": _settings.internal_api_secret},
            )
        if r.status_code == 200:
            data = r.json()
            fresh: dict[str, str] = {item["code"]: item["label"] for item in data}
            if fresh:
                _cache = fresh
                _cache_ts = now
                return dict(_cache)
        else:
            log.warning(
                "fuel_catalog: order_service returned %s — using cached labels",
                r.status_code,
            )
    except Exception as exc:
        log.warning("fuel_catalog: failed to fetch from order_service: %s", exc)

    # Возвращаем то, что есть в кэше (либо первоначальный хардкод)
    return dict(_cache)


async def get_fuel_codes() -> list[str]:
    """Вернуть отсортированный список кодов топлива."""
    labels = await get_fuel_labels()
    return sorted(labels.keys())
