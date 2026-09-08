"""Заявка на перевозку (ТЗ Ирины, 09.2026).

Архитектура: перевозка — это ``Order`` с ``order_kind='transport'`` плюс
строка 1:1 в ``transport_details``. Отдельной моделью её не делали намеренно:
всё, что ТЗ требует «в общем ряду» — список заявок, счётчики вкладок, статусы
new → accepted → delivered, номера ТТН, журнал действий (order_audit), чат
заявки — уже реализовано на Order. Параллельная сущность потребовала бы
дублировать это целиком.

Поля Order под перевозку:

* ``client_id`` — оформивший менеджер (колонка NOT NULL); в списке заявок
  вместо имени показывается «ПЕРЕВОЗКА» (см. buyer_info);
* ``fuel_type`` — код из каталога или пустая строка: по ТЗ вид топлива можно
  не указывать, а колонка NOT NULL;
* ``volume_requested`` — литры (0, если не указаны);
* ``delivery_address`` — текст маршрута «откуда → куда», чтобы общий список
  заявок оставался читаемым без спец-обработки.

Права: создают и правят только менеджер и админ; видит ещё водитель
перевозок (см. transport_driver); клиент — никогда.
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import TokenUser
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.order import Order, OrderKind, OrderStatus, PaymentType
from app.models.transport import (
    RoutePointKind, TransportBase, TransportClientObject, TransportDetail, TransportType,
)
from app.models.order_status_log import OrderStatusLog
from app.schemas.order import OrderStatusTransitionRequest
from app.schemas.transport import (
    TransportDeliverRequest, TransportOrderCreateRequest, TransportOrderUpdateRequest,
)
from app.services import fuel_type_service, order_audit, transport_driver
from app.services.order_number import generate_order_number
from app.services.transport_formulas import recompute, supplier_payments_total

log = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_DRIVER = "driver"
STAFF_ROLES = (ROLE_MANAGER, ROLE_ADMIN)

#: Поля блока 2 — их видит и правит только staff (ТЗ: «виден только админам и
#: менеджерам»). Список один на весь модуль: и для записи, и для сокрытия.
BLOCK2_FIELDS = (
    "price_per_kg", "price_per_l", "density", "total_amount",
    "supplier_payments", "delivery_price", "delivery_paid",
    "driver_payment_amount", "driver_payment_percent",
)

#: Поля блока 1 — их видит водитель.
BLOCK1_FIELDS = (
    "transport_type", "client_object_id", "amount_kg", "amount_l", "desired_date_text",
)

MAX_WAYPOINTS = 3
MAX_SUPPLIER_PAYMENTS = 4


def _require_staff(actor: TokenUser) -> None:
    if actor.role not in STAFF_ROLES:
        raise ForbiddenError(
            "Заявки на перевозку создают и правят менеджер и администратор"
        )


# ── Маршрут ───────────────────────────────────────────────────────────────────


def _point_to_dict(point) -> dict | None:
    """RoutePoint (pydantic) → словарь для JSONB. None остаётся None."""
    if point is None:
        return None
    kind = getattr(point.kind, "value", point.kind)
    return {
        "kind": str(kind),
        "id": str(point.id) if point.id else None,
        "text": (point.text or "").strip() or None,
    }


def _point_from_dict(kind, point_id, text) -> dict | None:
    if not kind and not point_id and not text:
        return None
    return {
        "kind": str(getattr(kind, "value", kind) or ""),
        "id": str(point_id) if point_id else None,
        "text": text,
    }


async def _resolve_point_label(db: AsyncSession, point: dict | None) -> str:
    """Человекочитаемое название точки: из справочника, иначе введённый текст."""
    if not point:
        return ""
    kind = point.get("kind")
    if kind == RoutePointKind.BASE.value:
        return point.get("text") or "База"
    point_id = point.get("id")
    if point_id:
        try:
            pk = uuid.UUID(str(point_id))
        except ValueError:
            pk = None
        if pk is not None:
            model = (
                TransportBase if kind == RoutePointKind.OIL_DEPOT.value
                else TransportClientObject
            )
            row = (await db.execute(select(model).where(model.id == pk))).scalar_one_or_none()
            if row is not None:
                return row.name
    return point.get("text") or ""


async def build_route_text(db: AsyncSession, detail: TransportDetail) -> str:
    """«Откуда → точка → Куда» — кладётся в delivery_address заявки.

    Так перевозка читается в общем списке заявок без единой правки рендера:
    там, где у обычной заявки адрес доставки, у перевозки виден маршрут.
    """
    parts: list[str] = []
    start = await _resolve_point_label(db, _detail_point(detail, "from"))
    if start:
        parts.append(start)
    for wp in detail.waypoints or []:
        label = await _resolve_point_label(db, wp)
        if label:
            parts.append(label)
    end = await _resolve_point_label(db, _detail_point(detail, "to"))
    if end:
        parts.append(end)
    return " → ".join(parts)


def _detail_point(detail: TransportDetail, side: str) -> dict | None:
    return _point_from_dict(
        getattr(detail, f"route_{side}_kind"),
        getattr(detail, f"route_{side}_id"),
        getattr(detail, f"route_{side}_text"),
    )


def _apply_point(detail: TransportDetail, side: str, point) -> None:
    data = _point_to_dict(point) or {}
    setattr(detail, f"route_{side}_kind", data.get("kind"))
    raw_id = data.get("id")
    setattr(detail, f"route_{side}_id", uuid.UUID(raw_id) if raw_id else None)
    setattr(detail, f"route_{side}_text", data.get("text"))


def _normalize_waypoints(points) -> list[dict]:
    if not points:
        return []
    if len(points) > MAX_WAYPOINTS:
        raise ValidationError(
            f"Промежуточных точек может быть не больше {MAX_WAYPOINTS}"
        )
    return [p for p in (_point_to_dict(p) for p in points) if p]


def _normalize_supplier_payments(rows) -> list[dict]:
    """Оплаты поставщику: до 4 пар «сумма + дата». Пустые пары отбрасываем."""
    if not rows:
        return []
    if len(rows) > MAX_SUPPLIER_PAYMENTS:
        raise ValidationError(
            f"Оплат поставщику может быть не больше {MAX_SUPPLIER_PAYMENTS}"
        )
    out: list[dict] = []
    for row in rows:
        amount = (row or {}).get("amount")
        date = (row or {}).get("date")
        if amount in (None, "") and not date:
            continue
        if amount not in (None, ""):
            try:
                if Decimal(str(amount)) < 0:
                    raise ValidationError("Оплата поставщику не может быть отрицательной")
            except (ArithmeticError, ValueError):
                raise ValidationError("Некорректная сумма оплаты поставщику")
        out.append({"amount": str(amount) if amount not in (None, "") else None,
                    "date": date or None})
    return out


# ── Создание ──────────────────────────────────────────────────────────────────


async def create_transport_order(
    db: AsyncSession, data: TransportOrderCreateRequest, actor: TokenUser
) -> Order:
    _require_staff(actor)

    fuel_type = (data.fuel_type or "").strip()
    if fuel_type:
        # Вид топлива необязателен (ТЗ), но если указан — только из каталога.
        await fuel_type_service.validate_active(db, fuel_type)

    # Водитель перевозок: явный из запроса, иначе настроенный (Бурнаев).
    # Если резолв не удался — заявка создаётся без водителя, назначат руками.
    driver_id = data.driver_id or await transport_driver.resolve_transport_driver_id()

    order = Order(
        order_number=await generate_order_number(db, OrderKind.TRANSPORT),
        order_kind=OrderKind.TRANSPORT,
        client_id=actor.id,          # оформивший менеджер; в списке — «ПЕРЕВОЗКА»
        organization_id=None,
        manager_id=actor.id,
        driver_id=driver_id,
        fuel_type=fuel_type,         # "" = вид топлива не указан
        volume_requested=data.amount_l or 0,
        delivery_address="",         # заполним маршрутом после создания деталей
        desired_date=None,           # дата у перевозки — свободный текст
        payment_type=PaymentType.ON_DELIVERY,
        client_comment=data.comment,
        status=OrderStatus.NEW,
    )
    db.add(order)
    await db.flush()

    detail = TransportDetail(
        order_id=order.id,
        transport_type=data.transport_type.value,
        client_object_id=data.client_object_id,
        waypoints=_normalize_waypoints(data.waypoints),
        amount_kg=data.amount_kg,
        amount_l=data.amount_l,
        desired_date_text=(data.desired_date_text or "").strip() or None,
        delivery_paid=bool(data.delivery_paid),
    )
    _apply_point(detail, "from", data.route_from)
    _apply_point(detail, "to", data.route_to)

    _write_block2(detail, data, is_create=True)
    db.add(detail)
    await db.flush()

    order.delivery_address = await build_route_text(db, detail)

    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=None,
        to_status=OrderStatus.NEW,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка на перевозку создана",
    ))
    # CRM-44: перевозка — обычный Order, журнал действий пишется как у всех.
    order_audit.record(db, order.id, actor, order_audit.ACTION_CREATED)
    await db.flush()
    return await get_transport_order(db, order.id, actor)


def _write_block2(detail: TransportDetail, data, *, is_create: bool) -> None:
    """Записать поля блока 2 и досчитать производные по формулам ТЗ.

    Ручной ввод приоритетнее расчёта: recompute трогает только пустые поля.
    """
    for field in BLOCK2_FIELDS:
        if field in ("supplier_payments", "delivery_paid"):
            continue
        if is_create or field in data.model_fields_set:
            setattr(detail, field, getattr(data, field))

    if is_create or "supplier_payments" in data.model_fields_set:
        detail.supplier_payments = _normalize_supplier_payments(data.supplier_payments)
    if not is_create and "delivery_paid" in data.model_fields_set:
        detail.delivery_paid = bool(data.delivery_paid)

    computed = recompute({
        "amount_kg": detail.amount_kg,
        "amount_l": detail.amount_l,
        "density": detail.density,
        "price_per_kg": detail.price_per_kg,
        "price_per_l": detail.price_per_l,
        "total_amount": detail.total_amount,
        "driver_payment_amount": detail.driver_payment_amount,
        "driver_payment_percent": detail.driver_payment_percent,
    })
    detail.amount_l = computed["amount_l"]
    detail.total_amount = computed["total_amount"]
    detail.driver_payment_amount = computed["driver_payment_amount"]


# ── Чтение ────────────────────────────────────────────────────────────────────


async def get_transport_order(
    db: AsyncSession, order_id: uuid.UUID, actor: TokenUser
) -> Order:
    """Заявка на перевозку с деталями. Права — те же, что у обычной заявки."""
    order = (
        await db.execute(
            select(Order)
            .options(selectinload(Order.status_logs), selectinload(Order.transport))
            .where(Order.id == order_id, Order.is_archived == False)  # noqa: E712
        )
    ).scalar_one_or_none()
    if order is None or order.order_kind != OrderKind.TRANSPORT:
        raise NotFoundError("Заявка на перевозку не найдена")

    if actor.role not in STAFF_ROLES:
        # Водитель — только своя перевозка; клиент — никогда.
        if actor.role != ROLE_DRIVER or order.driver_id != actor.id:
            raise ForbiddenError()
    return order


async def detail_response(
    db: AsyncSession, order: Order, actor: TokenUser
) -> dict | None:
    """Детали перевозки под роль: блок 2 отдаём только staff."""
    detail = order.transport
    if detail is None:
        return None

    payload = {
        "transport_type": detail.transport_type,
        "client_object_id": detail.client_object_id,
        "route_from": _detail_point(detail, "from"),
        "route_to": _detail_point(detail, "to"),
        "waypoints": list(detail.waypoints or []),
        "amount_kg": detail.amount_kg,
        "amount_l": detail.amount_l,
        "desired_date_text": detail.desired_date_text,
    }
    if actor.role not in STAFF_ROLES:
        # Водитель видит только блок 1 — деньги перевозки внутренние.
        return payload

    for field in BLOCK2_FIELDS:
        payload[field] = getattr(detail, field)
    payload["supplier_payments"] = list(detail.supplier_payments or [])
    payload["supplier_paid_total"] = supplier_payments_total(detail.supplier_payments)
    return payload


# ── Правка ────────────────────────────────────────────────────────────────────


async def update_transport_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: TransportOrderUpdateRequest,
    actor: TokenUser,
) -> Order:
    """После отправки заявки правится ЛЮБОЕ поле (ТЗ, п. 3) — но только staff."""
    _require_staff(actor)
    order = await get_transport_order(db, order_id, actor)
    detail = order.transport
    if detail is None:
        raise NotFoundError("Детали перевозки не найдены")

    fields = data.model_fields_set

    if "fuel_type" in fields:
        fuel_type = (data.fuel_type or "").strip()
        if fuel_type:
            await fuel_type_service.validate_active(db, fuel_type)
        order.fuel_type = fuel_type
    if "comment" in fields:
        order.client_comment = data.comment
    if "driver_id" in fields:
        order.driver_id = data.driver_id

    if "transport_type" in fields and data.transport_type is not None:
        detail.transport_type = data.transport_type.value
    if "client_object_id" in fields:
        detail.client_object_id = data.client_object_id
    if "route_from" in fields:
        _apply_point(detail, "from", data.route_from)
    if "route_to" in fields:
        _apply_point(detail, "to", data.route_to)
    if "waypoints" in fields:
        detail.waypoints = _normalize_waypoints(data.waypoints)
    if "amount_kg" in fields:
        detail.amount_kg = data.amount_kg
    if "amount_l" in fields:
        detail.amount_l = data.amount_l
    if "desired_date_text" in fields:
        detail.desired_date_text = (data.desired_date_text or "").strip() or None

    _write_block2(detail, data, is_create=False)

    # Литры заявки и текст маршрута — производные: держим их в синхроне,
    # иначе общий список заявок показывал бы старый маршрут.
    order.volume_requested = detail.amount_l or 0
    order.delivery_address = await build_route_text(db, detail)

    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=order.status,
        to_status=order.status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка на перевозку изменена",
    ))
    order_audit.record(
        db, order.id, actor, order_audit.ACTION_FIELD,
        field="transport", old_value=None, new_value="изменена",
    )
    await db.flush()
    return await get_transport_order(db, order_id, actor)


# ── Доставлено ────────────────────────────────────────────────────────────────


async def deliver_transport_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: TransportDeliverRequest,
    actor: TokenUser,
):
    """Окно «доставлено» водителя: маршрут и дата обязательны и правятся.

    Сохраняем подтверждённый водителем маршрут/дату, затем переводим заявку в
    DELIVERED штатным ``transition_status`` — оттуда идут номер ТТН (общий ряд
    с юрлицами), журнал действий, история статусов и событие уведомления.
    """
    order = await get_transport_order(db, order_id, actor)
    detail = order.transport
    if detail is None:
        raise NotFoundError("Детали перевозки не найдены")

    if not (data.desired_date_text or "").strip():
        raise ValidationError("Укажите дату доставки")
    if _point_to_dict(data.route_from) is None or _point_to_dict(data.route_to) is None:
        raise ValidationError("Укажите маршрут: откуда и куда")

    _apply_point(detail, "from", data.route_from)
    _apply_point(detail, "to", data.route_to)
    detail.waypoints = _normalize_waypoints(data.waypoints)
    detail.desired_date_text = data.desired_date_text.strip()
    order.delivery_address = await build_route_text(db, detail)
    await db.flush()

    # Импорт внутри функции: order_service не должен зависеть от transport_service
    # на уровне модуля — иначе циклический импорт.
    from app.services import order_service

    return await order_service.transition_status(
        db,
        order_id,
        OrderStatusTransitionRequest(
            to_status=OrderStatus.DELIVERED,
            comment=(data.comment or "").strip() or None,
            idempotency_key=data.idempotency_key,
        ),
        actor,
        idempotency_key=str(data.idempotency_key) if data.idempotency_key else None,
    )


__all__ = [
    "BLOCK1_FIELDS",
    "BLOCK2_FIELDS",
    "MAX_SUPPLIER_PAYMENTS",
    "MAX_WAYPOINTS",
    "TransportType",
    "build_route_text",
    "create_transport_order",
    "deliver_transport_order",
    "detail_response",
    "get_transport_order",
    "update_transport_order",
]
