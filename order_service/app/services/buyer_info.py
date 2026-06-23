"""Резолв имени покупателя (организация / ФИО клиента) для отображения в заявках.

Правки 2026-06-23: в списке и карточке заявки нужно показывать «кто сделал
заявку» — название организации, иначе ФИО физлица. Имя тянется из auth_service
батчем (один запрос на список) и навешивается транзиентным атрибутом
order.buyer_name, который сериализуется в OrderResponse/OrderListResponse.

Недоступность auth — не критична: buyer_name остаётся None, заявка отображается
без имени (лучше без подписи, чем 500 на списке заявок).
"""
import logging
import uuid

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

AUTH_SERVICE_URL = get_settings().auth_service_url
INTERNAL_SECRET = get_settings().internal_api_secret


async def _fetch_names(items: list[dict]) -> dict[str, str]:
    """Запросить имена покупателей батчем. Ключ результата — str(client_id)+|+org_id."""
    base = AUTH_SERVICE_URL.rstrip("/")
    headers = {"X-Internal-Secret": INTERNAL_SECRET}
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.post(
            f"{base}/api/v1/internal/orders/buyer-names",
            json={"items": items},
            headers=headers,
        )
        r.raise_for_status()
        out: dict[str, str] = {}
        for row in r.json():
            key = f"{row['client_id']}|{row.get('organization_id') or ''}"
            if row.get("name"):
                out[key] = row["name"]
        return out


def _key(client_id: uuid.UUID, organization_id: uuid.UUID | None) -> str:
    return f"{client_id}|{organization_id or ''}"


async def attach_buyer_names(orders: list) -> None:
    """Навесить order.buyer_name на каждую заявку списка (один батч-запрос)."""
    for o in orders:
        o.buyer_name = None
    if not orders:
        return
    # Уникальные пары (client, org) — чтобы не дублировать в запросе.
    seen: set[str] = set()
    items: list[dict] = []
    for o in orders:
        k = _key(o.client_id, o.organization_id)
        if k in seen:
            continue
        seen.add(k)
        items.append({
            "client_id": str(o.client_id),
            "organization_id": str(o.organization_id) if o.organization_id else None,
        })
    try:
        names = await _fetch_names(items)
    except Exception as exc:
        log.warning("attach_buyer_names failed (non-fatal): %s", exc)
        return
    for o in orders:
        o.buyer_name = names.get(_key(o.client_id, o.organization_id))


async def attach_buyer_name_one(order) -> None:
    """Навесить buyer_name на одну заявку (карточка)."""
    await attach_buyer_names([order])
