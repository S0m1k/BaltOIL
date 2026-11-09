"""Поиск заявок по всей системе и порядок «доставленных» (правки 2026-11-09).

Поиск: номер заявки, номер ТТН, адрес доставки, контакт приёмки (имя/телефон) и
«название» — организация или ФИО клиента. Названия живут в auth_service, поэтому
по тексту мы спрашиваем у него идентификаторы подходящих организаций/клиентов и
ограничиваем ими заявки. Условие накладывается ПОВЕРХ видимости роли
(`_visibility_conditions`), так что чужие заявки через поиск не появляются.

Порядок доставленных: по моменту ПЕРВОЙ отгрузки, а не по номеру заявки. ТТН
выдаётся в момент первого перехода в «доставлена», поэтому хронология отгрузок =
хронология ТТН.
Сравнивать сами номера напрямую нельзя: у Ю/Ф/Л свои счётчики (Ф000005 не «раньше»
Ю000042), а момент отгрузки у них общий.
"""
from __future__ import annotations

import logging
import re

import httpx
from sqlalchemy import and_, func, or_, select

from app.config import get_settings
from app.models.order import Order, OrderStatus
from app.models.order_status_log import OrderStatusLog

log = logging.getLogger(__name__)

#: Короче двух символов искать бессмысленно: выдача — вся система.
MIN_SEARCH_LEN = 2

_LIKE_SPECIAL = re.compile(r"([%_\\])")


def normalize_query(q: str | None) -> str | None:
    """Обрезать пробелы; пустой запрос = «без поиска»."""
    text = (q or "").strip()
    return text or None


def like_pattern(text: str) -> str:
    """«%текст%» с экранированием спецсимволов LIKE («100%» ищется как текст)."""
    return "%" + _LIKE_SPECIAL.sub(r"\\\1", text) + "%"


async def find_buyer_ids(text: str) -> tuple[list[str], list[str]]:
    """Идентификаторы клиентов и организаций, подходящих под текст (auth_service).

    Недоступность auth не должна ронять поиск: без названий остаётся поиск по
    номеру/адресу/ТТН/контакту, а в лог уходит предупреждение.
    """
    settings = get_settings()
    base = settings.auth_service_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{base}/api/v1/internal/orders/find-buyers",
                json={"q": text},
                headers={"X-Internal-Secret": settings.internal_api_secret},
            )
            r.raise_for_status()
            data = r.json()
        return list(data.get("client_ids", [])), list(data.get("organization_ids", []))
    except Exception as exc:  # noqa: BLE001 — поиск деградирует, а не падает
        log.warning("find_buyer_ids failed (поиск без названий): %s", exc)
        return [], []


def build_search_condition(text: str, client_ids: list, organization_ids: list):
    """SQL-условие «заявка подходит под текст». `text` — уже нормализованный."""
    pattern = like_pattern(text)
    conditions = [
        Order.order_number.ilike(pattern, escape="\\"),
        Order.ttn_number.ilike(pattern, escape="\\"),
        Order.delivery_address.ilike(pattern, escape="\\"),
        Order.contact_person_name.ilike(pattern, escape="\\"),
    ]
    digits = re.sub(r"\D", "", text)
    # Телефон ищем по цифрам и только от 4 штук: «12» в адресе не должно
    # цеплять каждый номер, где есть «12».
    if len(digits) >= 4:
        conditions.append(
            func.regexp_replace(Order.contact_person_phone, r"\D", "", "g").like(f"%{digits}%")
        )
    if client_ids:
        conditions.append(Order.client_id.in_(client_ids))
    if organization_ids:
        conditions.append(Order.organization_id.in_(organization_ids))
    return or_(*conditions)


def delivered_at_expr():
    """Момент отгрузки: ПЕРВЫЙ переход заявки в DELIVERED (история статусов).

    Именно первый: ТТН выдаётся при первой отгрузке и дальше не меняется, а у части
    заявок переходов в «доставлена» несколько (админ вернул заявку на правку и
    доставил снова) — по последнему такая заявка «прыгала» бы вверх списка, хотя её
    ТТН старый. На проде порядок по первому переходу совпадает с нумерацией ТТН.

    У заявок без записи в истории (старые данные) откатываемся на updated_at.
    """
    moment = (
        select(func.min(OrderStatusLog.created_at))
        .where(
            and_(
                OrderStatusLog.order_id == Order.id,
                OrderStatusLog.to_status == OrderStatus.DELIVERED,
            )
        )
        .correlate(Order)
        .scalar_subquery()
    )
    return func.coalesce(moment, Order.updated_at)


def order_by_clauses(status: OrderStatus | None) -> list:
    """Порядок выдачи: доставленные — по хронологии отгрузок, остальные — по созданию."""
    if status == OrderStatus.DELIVERED:
        return [delivered_at_expr().desc(), Order.ttn_number.desc().nulls_last(), Order.created_at.desc()]
    return [Order.created_at.desc()]
