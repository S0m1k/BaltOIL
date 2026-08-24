"""Номера ТТН заявок из order_service — батчем, для складского отчёта.

Операции склада (fuel_transactions) хранят order_id/order_number, но не номер
ТТН: он присваивается заявке в order_service в момент отметки «Доставлена».
Тянем его ОДНИМ запросом на весь отчёт, а не по операции (иначе N+1).

Недоступность order_service не критична: колонка «№ ТТН» останется пустой,
отчёт всё равно сформируется.
"""
import logging
import uuid

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

# Ограничение на размер батча совпадает с лимитом internal-эндпоинта
# order_service (POST /internal/orders/ttn-numbers).
MAX_BATCH = 10_000


async def fetch_ttn_numbers(order_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """{order_id: ttn_number} для заявок, у которых ТТН присвоена."""
    unique_ids = list(dict.fromkeys(oid for oid in order_ids if oid))
    if not unique_ids:
        return {}
    if len(unique_ids) > MAX_BATCH:
        log.warning("ttn_lookup: %s заявок — берём первые %s", len(unique_ids), MAX_BATCH)
        unique_ids = unique_ids[:MAX_BATCH]

    _settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{_settings.order_service_url}/api/v1/internal/orders/ttn-numbers",
                json={"order_ids": [str(oid) for oid in unique_ids]},
                headers={"X-Internal-Secret": _settings.internal_api_secret},
            )
        r.raise_for_status()
    except Exception as exc:
        log.warning("ttn_lookup: не удалось получить номера ТТН (не критично): %s", exc)
        return {}

    out: dict[uuid.UUID, str] = {}
    for row in r.json():
        ttn = row.get("ttn_number")
        if not ttn:
            continue
        try:
            out[uuid.UUID(str(row["order_id"]))] = ttn
        except (KeyError, ValueError):
            continue
    return out
