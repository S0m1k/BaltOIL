import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import selectinload

import httpx
import jwt as jose_jwt

from app.config import get_settings as _get_settings
from app.models.order import Order, OrderStatus, OrderKind, PaymentType
from app.services import fuel_type_service
from app.models.order_status_log import OrderStatusLog
from app.core.dependencies import TokenUser
from app.core.status_machine import validate_transition
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError, StatusTransitionError
from app.schemas.order import OrderCreateRequest, OrderUpdateRequest, OrderStatusTransitionRequest, RescheduleRequest, PricePreviewRequest
from app.services.order_number import generate_order_number, generate_ttn_number
from app.services.payment_service import (
    recompute_and_save,
    attach_payment_totals,
    attach_payment_totals_one,
)
from app.services import document_service
from app.services import contract_service
from app.services.buyer_info import attach_buyer_names, attach_buyer_name_one
from app.services.client_context import get_client_context, get_user_organization_ids
from app.services.payment_type_rules import validate_payment_type
from app.services.pricing_service import compute_expected_amount, compute_price_breakdown, compute_delivery_cost, compute_zone_delivery_cost, get_tariff, get_default_tariff
from app.services.zone_pricing import resolve_zone
from app.core.events import publish_order_event

log = logging.getLogger(__name__)

# Порог объёма (л): при >= этого значения счёт не выставляется автоматически —
# менеджер получает уведомление и выставляет вручную (Д4, решение 2026-06-05).
LARGE_VOLUME_THRESHOLD_L = 3000

# Минимальный объём заявки (л) для клиента. Менеджер/админ может оформить
# заявку на любой объём (правка заказчика 2026-06-16).
MIN_VOLUME_L = 300


async def _notify_large_volume(order: Order, body: str | None = None) -> None:
    """Уведомить менеджеров: заявка >= порога, счёт нужно выставить вручную."""
    await publish_order_event({
        "event": "order_large_volume",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": None,
        "status": order.status.value,
        "title": f"Заявка №{order.order_number}: объём ≥ 3000 л",
        "body": body or "Счёт не выставлен автоматически — выставьте вручную.",
    })


def _make_service_token(actor: TokenUser) -> str:
    _settings = _get_settings()
    return jose_jwt.encode(
        {
            "sub": str(actor.id),
            "role": actor.role,
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        _settings.jwt_secret_key,
        algorithm=_settings.jwt_algorithm,
    )


async def _notify_driver(order: Order, actor: TokenUser, title: str, body: str) -> None:
    """Публикует событие уведомления водителю через Redis pub/sub."""
    await publish_order_event({
        "event": "order_status",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": str(order.driver_id) if order.driver_id else None,
        "status": order.status.value,
        "title": title,
        "body": body,
    })


async def _auto_record_delivery(order: Order, actor: TokenUser) -> None:
    """Создать departure-транзакцию в delivery_service при переводе заявки в DELIVERED.

    Если delivery_service недоступен — raise StatusTransitionError (fail-closed).
    """
    try:
        _settings = _get_settings()
        token = _make_service_token(actor)
        volume = float(order.volume_delivered or order.volume_requested)
        payload = {
            "order_id": str(order.id),
            "driver_id": str(order.driver_id),
            "inv_fuel_type": order.fuel_type if order.fuel_type else None,
            "inv_order_number": order.order_number,
            "inv_client_id": str(order.client_id),
            "volume_planned": volume,
            "delivery_address": order.delivery_address or "",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{_settings.delivery_service_url}/api/v1/trips/auto-start",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code in (200, 201):
            return
        detail = r.json().get("detail", f"Ошибка сервиса доставки: {r.status_code}")
        raise StatusTransitionError(detail)
    except StatusTransitionError:
        raise
    except Exception as exc:
        # repr, не str: у httpx-таймаутов (ReadTimeout и др.) str(exc) пустой.
        log.error("_auto_record_delivery failed for order %s: %r", order.id, exc)
        raise StatusTransitionError(
            "Не удалось зафиксировать доставку: сервис доставки недоступен. Попробуйте позже."
        )


ROLE_CLIENT = "client"
ROLE_DRIVER = "driver"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"


def _with_logs(query):
    return query.options(selectinload(Order.status_logs))


async def get_order(
    db: AsyncSession, order_id: uuid.UUID, actor: TokenUser, *, lock: bool = False
) -> Order:
    query = _with_logs(
        select(Order).where(Order.id == order_id, Order.is_archived == False)  # noqa: E712
    )
    if lock:
        # FOR UPDATE OF orders: сериализует параллельные переходы статуса,
        # чтобы два запроса не прошли validate_transition по одному состоянию.
        # selectinload(status_logs) грузится отдельным запросом — блокировки не требует.
        query = query.with_for_update(of=Order)
    result = await db.execute(query)
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена")

    # Клиент видит только свои заявки
    if actor.role == ROLE_CLIENT and order.client_id != actor.id:
        raise ForbiddenError()
    # Водитель: ТТН-Л видна только назначенному; обычные — свои + пул NEW
    if actor.role == ROLE_DRIVER:
        if order.order_kind == OrderKind.TTN_L and order.driver_id != actor.id:
            raise ForbiddenError()
        if order.order_kind != OrderKind.TTN_L:
            # видна если назначена ему или это свободная NEW
            is_assigned = order.driver_id == actor.id
            is_free_new = order.status == OrderStatus.NEW and order.driver_id is None
            if not is_assigned and not is_free_new:
                raise ForbiddenError()

    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


def _visibility_conditions(actor: TokenUser, org_ids: list | None = None) -> list:
    """Условия видимости заявок по роли — общие для списка и счётчиков.

    Для клиента: свои заявки (client_id) + все заявки его организаций
    (organization_id ∈ org_ids) — member видит весь учёт по юрлицу.
    """
    conditions = [Order.is_archived == False]  # noqa: E712

    if actor.role == ROLE_CLIENT:
        if org_ids:
            conditions.append(
                or_(Order.client_id == actor.id, Order.organization_id.in_(org_ids))
            )
        else:
            conditions.append(Order.client_id == actor.id)
    elif actor.role == ROLE_DRIVER:
        # Водитель видит:
        # - свои заявки (driver_id == actor.id) всех видов
        # - свободные NEW не-TTN-L (биржа: driver_id IS NULL, kind != ttn_l)
        conditions.append(
            or_(
                Order.driver_id == actor.id,
                and_(
                    Order.status == OrderStatus.NEW,
                    Order.driver_id == None,  # noqa: E711
                    Order.order_kind != OrderKind.TTN_L,
                ),
            )
        )
    # Manager/admin видят все
    return conditions


async def count_orders_by_status(
    db: AsyncSession,
    actor: TokenUser,
) -> dict[str, int]:
    """Количество заявок по каждому статусу в пределах видимости роли.
    Используется для бейджей на вкладках реестра (правка заказчика 2026-06-16)."""
    org_ids = await get_user_organization_ids(actor.id) if actor.role == ROLE_CLIENT else None
    conditions = _visibility_conditions(actor, org_ids)
    result = await db.execute(
        select(Order.status, func.count())
        .where(and_(*conditions))
        .group_by(Order.status)
    )
    return {status.value: count for status, count in result.all()}


async def list_orders(
    db: AsyncSession,
    actor: TokenUser,
    *,
    status: OrderStatus | None = None,
    driver_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Order]:
    org_ids = await get_user_organization_ids(actor.id) if actor.role == ROLE_CLIENT else None
    conditions = _visibility_conditions(actor, org_ids)

    if status:
        conditions.append(Order.status == status)
    if driver_id and actor.role in (ROLE_MANAGER, ROLE_ADMIN):
        conditions.append(Order.driver_id == driver_id)
    if client_id and actor.role in (ROLE_MANAGER, ROLE_ADMIN):
        conditions.append(Order.client_id == client_id)

    result = await db.execute(
        _with_logs(
            select(Order).where(and_(*conditions))
            .order_by(Order.created_at.desc())
            .offset(offset).limit(limit)
        )
    )
    orders = list(result.scalars().all())
    await attach_payment_totals(db, orders)
    await attach_buyer_names(orders)
    return orders


async def preview_price(
    db: AsyncSession,
    data: PricePreviewRequest,
    actor: TokenUser,
) -> dict:
    """Read-only price breakdown for the order create form. No DB writes."""
    from decimal import Decimal as _Decimal
    is_staff = actor.role in (ROLE_MANAGER, ROLE_ADMIN)

    if is_staff and data.client_id:
        client_id = data.client_id
    else:
        client_id = actor.id

    ctx = await get_client_context(client_id, data.organization_id)
    bd = await compute_price_breakdown(db, data.fuel_type, data.volume, ctx.tariff_id, ctx.client_type, ctx.fuel_coefficient)

    pricing_warning = not bd["tariff_found"] or bd["price_per_liter"] is None

    # Zone resolution — fail-open
    zone_name = None
    zone_cost_coefficient = None
    delivery_cost = None
    try:
        if data.delivery_lat is not None and data.delivery_lon is not None:
            zone_info = await resolve_zone(data.delivery_lat, data.delivery_lon)
            if zone_info:
                zone_name = zone_info["name"]
                zone_cost_coefficient = float(zone_info["cost_coefficient"])
                delivery_cost = compute_zone_delivery_cost(
                    zone_info,
                    bd["base_delivery_cost"],
                    data.volume,
                    ctx.delivery_coefficient,
                )
    except Exception as exc:
        log.warning("preview_price: zone resolution failed (non-fatal): %s", exc)

    fuel_subtotal = bd["fuel_subtotal"]
    if fuel_subtotal is not None:
        total = fuel_subtotal + (delivery_cost or _Decimal("0"))
    else:
        total = None
        pricing_warning = True

    return {
        "fuel_type": data.fuel_type,
        "volume": data.volume,
        "price_per_liter": bd["price_per_liter"],
        "discount_pct": bd["discount_pct"],
        "effective_price_per_liter": bd["effective_price_per_liter"],
        "fuel_subtotal": fuel_subtotal,
        "zone_name": zone_name,
        "zone_cost_coefficient": zone_cost_coefficient,
        "base_delivery_cost": bd["base_delivery_cost"],
        "delivery_cost": delivery_cost,
        "total": total,
        "pricing_warning": pricing_warning,
    }


async def create_order(
    db: AsyncSession,
    data: OrderCreateRequest,
    actor: TokenUser,
) -> Order:
    is_staff = actor.role in (ROLE_MANAGER, ROLE_ADMIN)

    if not is_staff and actor.role != ROLE_CLIENT:
        raise ForbiddenError("Создание заявок доступно клиентам, менеджерам и администраторам")

    # Минимальный объём — только для клиентов; менеджер/админ не ограничен
    if not is_staff and float(data.volume_requested) < MIN_VOLUME_L:
        raise ValidationError(f"Минимальный объём заказа — {MIN_VOLUME_L} литров")

    # ТТН-Л создаёт только менеджер/админ, водитель обязателен
    if data.is_ttn_l:
        if not is_staff:
            raise ForbiddenError("ТТН-Л может создать только менеджер или администратор")
        if not data.driver_id:
            raise ValidationError("Для ТТН-Л необходимо указать водителя")

    # Менеджер/Админ может создать заявку от имени клиента
    if is_staff:
        client_id = data.client_id or actor.id
    else:
        if data.client_id:
            raise ForbiddenError("Клиент не может указывать client_id")
        if data.driver_id:
            raise ForbiddenError("Клиент не может назначать водителя")
        client_id = actor.id

    # Организация (юрлицо), от имени которой создаётся заявка. NULL = «как физлицо».
    organization_id = data.organization_id

    # Fetch client/organization context (client_type, credit_allowed, tariff_id) from auth_service.
    # При organization_id auth проверяет членство клиента (400 если не участник).
    # Fails with 503 if auth_service is unreachable — we never silently skip this check.
    ctx = await get_client_context(client_id, organization_id)

    # Определить вид заявки
    if data.is_ttn_l:
        order_kind = OrderKind.TTN_L
    elif ctx.client_type == "individual":
        order_kind = OrderKind.INDIVIDUAL
    else:
        order_kind = OrderKind.COMPANY

    # Физлица всегда платят по факту (on_delivery) — выбор игнорируется
    if ctx.client_type == "individual":
        data.payment_type = PaymentType.ON_DELIVERY
    else:
        # Validate payment_type against role × client_type × credit_allowed matrix
        validate_payment_type(
            data.payment_type,
            actor_role=actor.role,
            client_type=ctx.client_type,
            credit_allowed=ctx.credit_allowed,
        )

    # Дата доставки не может быть в прошлом
    if data.desired_date:
        desired_utc = data.desired_date if data.desired_date.tzinfo else data.desired_date.replace(tzinfo=timezone.utc)
        if desired_utc < datetime.now(timezone.utc):
            raise ValidationError("Желаемая дата доставки не может быть в прошлом")

    # Валидация вида топлива по каталогу (hard-fail: неизвестный/неактивный код → 422)
    await fuel_type_service.validate_active(db, data.fuel_type)

    # Дополнительная проверка наличия топлива на складе (fail-open: сетевая ошибка не блокирует)
    in_stock = await fuel_type_service.fetch_in_stock_codes()
    if in_stock is not None and data.fuel_type not in in_stock:
        raise ValidationError(
            f"Топливо «{data.fuel_type}» временно отсутствует на складе. "
            "Пожалуйста, выберите другой вид топлива или свяжитесь с менеджером."
        )

    order_number = await generate_order_number(db, order_kind)

    # Compute expected_amount from tariff (None if tariff not configured — non-fatal)
    expected_amount = await compute_expected_amount(
        db, data.fuel_type, data.volume_requested, ctx.tariff_id, ctx.client_type,
        ctx.fuel_coefficient,
    )

    # Зональная стоимость доставки — fail-open (не блокирует создание заявки)
    resolved_zone_id = None
    resolved_zone_name = None
    delivery_cost = None
    delivery_lat = data.delivery_lat if data.delivery_lat is not None else None
    delivery_lon = data.delivery_lon if data.delivery_lon is not None else None

    if delivery_lat is not None and delivery_lon is not None:
        try:
            zone_info = await resolve_zone(delivery_lat, delivery_lon)
            if zone_info:
                resolved_zone_id = uuid.UUID(zone_info["zone_id"])
                resolved_zone_name = zone_info["name"]
                if zone_info.get("delivery_price") is not None:
                    # Фиксированная цена доставки по зоне — тариф не нужен
                    delivery_cost = compute_zone_delivery_cost(
                        zone_info, None, data.volume_requested, ctx.delivery_coefficient,
                    )
                else:
                    # Legacy: ставка тарифа за литр × коэффициент зоны
                    tariff = (
                        await get_tariff(db, ctx.tariff_id)
                        if ctx.tariff_id
                        else await get_default_tariff(db, ctx.client_type)
                    )
                    if tariff is not None:
                        delivery_cost = compute_zone_delivery_cost(
                            zone_info,
                            tariff.base_delivery_cost,
                            data.volume_requested,
                            ctx.delivery_coefficient,
                        )
                if delivery_cost is not None:
                    if expected_amount is not None:
                        expected_amount = expected_amount + delivery_cost
                    else:
                        expected_amount = delivery_cost
        except Exception as exc:
            log.warning("Zone pricing failed for order (non-fatal): %s", exc)

    # Согласование заявок (правки 2026-06-16):
    # - Физ лица: ВСЕ заявки клиента уходят на согласование менеджера.
    # - Юр лица: только строго > 3000 л.
    # Водители заявку на согласовании не видят и не могут взять.
    # Заявки, созданные менеджером/админом, согласования не требуют.
    needs_approval = (
        not is_staff
        and order_kind != OrderKind.TTN_L
        and (
            ctx.client_type == "individual"
            or float(data.volume_requested) > LARGE_VOLUME_THRESHOLD_L
        )
    )
    initial_status = OrderStatus.AWAITING_MANAGER if needs_approval else OrderStatus.NEW

    order = Order(
        order_number=order_number,
        order_kind=order_kind,
        client_id=client_id,
        organization_id=organization_id,
        manager_id=actor.id if is_staff else None,
        driver_id=data.driver_id if is_staff else None,
        fuel_type=data.fuel_type,
        volume_requested=data.volume_requested,
        delivery_address=data.delivery_address,
        desired_date=data.desired_date,
        contact_person_name=data.contact_person_name,
        contact_person_phone=data.contact_person_phone,
        payment_type=data.payment_type,
        expected_amount=expected_amount,
        client_comment=data.client_comment,
        manager_comment=data.manager_comment if is_staff else None,
        status=initial_status,
        delivery_lat=delivery_lat,
        delivery_lon=delivery_lon,
        delivery_zone_id=resolved_zone_id,
        delivery_zone_name=resolved_zone_name,
        delivery_cost=delivery_cost,
        # Only manager/admin may mark an order as debt (allow_delivery_unpaid)
        allow_delivery_unpaid=data.allow_delivery_unpaid if is_staff else False,
    )
    db.add(order)
    await db.flush()

    # Лог: создание
    if needs_approval:
        if ctx.client_type == "individual":
            create_comment = "Заявка создана — ожидайте звонка менеджера"
        else:
            create_comment = "Заявка создана — объём > 3000 л, требуется согласование менеджера"
    elif is_staff:
        create_comment = "Заявка создана менеджером"
    else:
        create_comment = "Заявка создана"
    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=None,
        to_status=initial_status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment=create_comment,
    ))

    await db.flush()

    # Auto-document: предварительный счёт при создании любой не-ttn_l заявки.
    # Порог 3000 л (Д4): крупные заявки не выставляются автоматически — менеджер
    # получает уведомление и выставляет счёт вручную. ttn_l счетов не имеет.
    if order.order_kind != OrderKind.TTN_L:
        if float(order.volume_requested) >= LARGE_VOLUME_THRESHOLD_L:
            try:
                notify_body = (
                    "Заявка ожидает согласования — проверьте её, выставьте счёт "
                    "и нажмите «Согласовать», чтобы передать водителям."
                    if needs_approval
                    else "Счёт не выставлен автоматически — выставьте вручную."
                )
                await _notify_large_volume(order, notify_body)
            except Exception as exc:
                log.warning("Large-volume notify failed for order %s: %s", order.id, exc)
        else:
            try:
                await document_service.generate_invoice(db, order, actor)
            except Exception as exc:
                log.warning("Auto-invoice failed for order %s: %s", order.id, exc)

    # Auto-contract: для клиента-юрлица без активного договора формируем договор
    # поставки. Не блокируем заявку — любая ошибка только логируется.
    # Физлица и ttn_l пропускаются тихо.
    if ctx.client_type == "company" and order.order_kind != OrderKind.TTN_L:
        try:
            existing = await contract_service.get_active_contract(db, client_id, organization_id)
            if existing is None:
                await contract_service.create_contract(db, client_id, actor, organization_id)
        except Exception as exc:
            log.warning("Auto-contract failed for client %s org %s (order %s): %s",
                        client_id, organization_id, order.id, exc)

    # Re-fetch with eager-loaded status_logs
    result = await db.execute(
        _with_logs(select(Order).where(Order.id == order.id))
    )
    order = result.scalar_one()

    await publish_order_event({
        "event": "order_created",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": str(order.driver_id) if order.driver_id else None,
        "status": order.status.value,
        "title": f"Заявка №{order.order_number} создана",
        "body": f"Новая заявка на доставку топлива: {order.delivery_address}",
    })

    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


# Поля, которые клиент может править в своей заявке (карандашики, правки 2026-06-11)
_CLIENT_EDITABLE = {"fuel_type", "volume_requested", "delivery_address", "desired_date",
                    "client_comment", "contact_person_name", "contact_person_phone"}
# Поля, которые водитель может править в назначенной ему заявке
_DRIVER_EDITABLE = {"fuel_type", "volume_requested", "delivery_address", "desired_date"}
# Статусы, в которых клиент/водитель ещё могут править заявку
_EDITABLE_STATUSES = {OrderStatus.NEW, OrderStatus.AWAITING_MANAGER, OrderStatus.ACCEPTED}


async def _recompute_expected_amount(db: AsyncSession, order: Order) -> None:
    """Пересчитать expected_amount и delivery_cost после смены топлива/объёма.

    Fail-open: при недоступности auth/delivery сервисов суммы остаются прежними.
    """
    try:
        ctx = await get_client_context(order.client_id, order.organization_id)
        expected = await compute_expected_amount(
            db, order.fuel_type, float(order.volume_requested),
            ctx.tariff_id, ctx.client_type, ctx.fuel_coefficient,
        )
        delivery_cost = order.delivery_cost
        if order.delivery_lat is not None and order.delivery_lon is not None:
            zone_info = await resolve_zone(order.delivery_lat, order.delivery_lon)
            if zone_info:
                base_rate = None
                if zone_info.get("delivery_price") is None:
                    tariff = (
                        await get_tariff(db, ctx.tariff_id)
                        if ctx.tariff_id
                        else await get_default_tariff(db, ctx.client_type)
                    )
                    base_rate = tariff.base_delivery_cost if tariff is not None else None
                recalc_delivery = compute_zone_delivery_cost(
                    zone_info, base_rate,
                    float(order.volume_requested), ctx.delivery_coefficient,
                )
                if recalc_delivery is not None:
                    delivery_cost = recalc_delivery
                    order.delivery_cost = recalc_delivery
        if expected is not None:
            order.expected_amount = expected + (delivery_cost or 0)
    except Exception as exc:
        log.warning("recompute_expected_amount failed for order %s (non-fatal): %s",
                    order.id, exc)


async def update_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: OrderUpdateRequest,
    actor: TokenUser,
) -> Order:
    order = await get_order(db, order_id, actor)

    is_staff = actor.role in (ROLE_MANAGER, ROLE_ADMIN)
    requested_fields = set(data.model_dump(exclude_unset=True, exclude_none=True).keys())

    # Матрица прав: staff — всё; клиент — свои заявки, ограниченные поля;
    # водитель — назначенные ему, ограниченные поля.
    if not is_staff:
        if actor.role == ROLE_CLIENT:
            if order.client_id != actor.id:
                raise ForbiddenError()
            extra = requested_fields - _CLIENT_EDITABLE
        elif actor.role == ROLE_DRIVER:
            if order.driver_id != actor.id:
                raise ForbiddenError("Редактировать можно только назначенную вам заявку")
            extra = requested_fields - _DRIVER_EDITABLE
        else:
            raise ForbiddenError()
        if extra:
            raise ForbiddenError(f"Недоступные для редактирования поля: {', '.join(sorted(extra))}")
        if order.status not in _EDITABLE_STATUSES:
            raise ValidationError("Заявку в этом статусе редактировать нельзя")

    if data.volume_requested is not None and data.volume_requested < 300:
        raise ValidationError("Минимальный объём заказа — 300 литров")
    if data.fuel_type is not None:
        await fuel_type_service.validate_active(db, data.fuel_type)
    if data.desired_date is not None:
        desired_utc = (data.desired_date if data.desired_date.tzinfo
                       else data.desired_date.replace(tzinfo=timezone.utc))
        if desired_utc < datetime.now(timezone.utc):
            raise ValidationError("Желаемая дата доставки не может быть в прошлом")

    # Track if we need to set pending_driver_ack
    was_accepted = order.status == OrderStatus.ACCEPTED
    changed = False
    # Ключи изменённых полей для индикации «что поменялось» (правки 2026-06-11)
    changed_keys: list[str] = []

    if data.manager_comment is not None:
        order.manager_comment = data.manager_comment
        changed = True
        changed_keys.append("comment")
    if data.desired_date is not None:
        order.desired_date = data.desired_date
        changed = True
        changed_keys.append("desired_date")
    if data.driver_id is not None:
        order.driver_id = data.driver_id
        changed = True
        changed_keys.append("driver")
    if data.expected_amount is not None:
        order.expected_amount = data.expected_amount
        changed = True
        changed_keys.append("amount")
    if data.trade_credit_contract_signed is not None:
        order.trade_credit_contract_signed = data.trade_credit_contract_signed
        changed = True
    if data.delivery_address is not None:
        order.delivery_address = data.delivery_address
        changed = True
        changed_keys.append("address")
    if data.fuel_type is not None:
        order.fuel_type = data.fuel_type
        changed = True
        changed_keys.append("fuel_type")
    if data.volume_requested is not None:
        order.volume_requested = data.volume_requested
        changed = True
        changed_keys.append("volume")
    if data.payment_type is not None:
        order.payment_type = data.payment_type
        changed = True
    if data.client_comment is not None:
        order.client_comment = data.client_comment
        changed = True
        changed_keys.append("comment")
    if data.contact_person_name is not None:
        order.contact_person_name = data.contact_person_name
        changed = True
    if data.contact_person_phone is not None:
        order.contact_person_phone = data.contact_person_phone
        changed = True
    if data.delivery_cost is not None:
        # Перекладываем долю доставки в expected_amount: топливная часть
        # (expected_amount − старый delivery_cost) сохраняется, доставка заменяется.
        # Пропускаем, если staff задал expected_amount явно (имеет приоритет) или
        # сумма ещё не рассчитана (нет тарифа — заполнит менеджер вручную).
        if data.expected_amount is None and order.expected_amount is not None:
            fuel_part = order.expected_amount - (order.delivery_cost or 0)
            order.expected_amount = fuel_part + data.delivery_cost
        order.delivery_cost = data.delivery_cost
        changed = True
        changed_keys.append("amount")
    if data.allow_delivery_unpaid is not None:
        order.allow_delivery_unpaid = data.allow_delivery_unpaid
        changed = True

    # Смена топлива/объёма меняет стоимость — пересчитываем, если сумма
    # не передана явно в этом же запросе (staff может задать вручную).
    if (("fuel_type" in changed_keys or "volume" in changed_keys)
            and data.expected_amount is None):
        await _recompute_expected_amount(db, order)

    # final_amount меняет цель — пересчитываем payment_status
    if data.final_amount is not None:
        order.final_amount = data.final_amount
        await recompute_and_save(db, order)
        changed = True
        changed_keys.append("amount")

    # Единый счёт (Д4 2026-06-23): если staff поменял объём/стоимость/сумму —
    # перевыпускаем счёт с теми же номером и датой, но новыми цифрами. Только для
    # staff и только если суммовые поля затронуты (карандашики клиента/водителя
    # сумму не меняют до согласования). Ошибка не блокирует сохранение заявки.
    _amount_touched = bool({"amount", "volume", "fuel_type"} & set(changed_keys))
    if is_staff and _amount_touched and order.order_kind != OrderKind.TTN_L:
        try:
            async with db.begin_nested():
                await document_service.regenerate_invoice(db, order, actor)
        except Exception as exc:
            log.warning("Invoice regen on staff edit failed for order %s: %s", order.id, exc)

    # Если заявка была в ACCEPTED и что-то изменил НЕ водитель — водитель должен
    # подтвердить (свои изменения водитель не подтверждает, правки 2026-06-11).
    if was_accepted and changed and actor.role != ROLE_DRIVER:
        order.pending_driver_ack = True
        merged = list(order.pending_changed_fields or [])
        for k in changed_keys:
            if k not in merged:
                merged.append(k)
        order.pending_changed_fields = merged

    if changed:
        db.add(OrderStatusLog(
            order_id=order.id,
            from_status=order.status,
            to_status=order.status,
            changed_by_id=actor.id,
            changed_by_role=actor.role,
            comment="Заявка изменена",
        ))

    # Re-fetch с eager-загрузкой status_logs (как в create/transition): иначе после
    # flush server-side updated_at (onupdate) протухает и сериализация ответа лезет
    # в lazy-load вне async-контекста → MissingGreenlet → 500.
    await db.flush()
    result = await db.execute(
        _with_logs(select(Order).where(Order.id == order_id))
    )
    order = result.scalar_one()

    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


async def claim_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser,
) -> Order:
    """Водитель берёт свободную заявку из биржи (NEW, driver_id IS NULL, не ТТН-Л).
    Атомарная операция: SELECT FOR UPDATE защищает от гонки двух водителей.
    Переход NEW → ACCEPTED, driver_id устанавливается.
    """
    if actor.role != ROLE_DRIVER:
        raise ForbiddenError("Взять заявку может только водитель")

    result = await db.execute(
        _with_logs(
            select(Order).where(
                Order.id == order_id,
                Order.is_archived == False,  # noqa: E712
                Order.status == OrderStatus.NEW,
                Order.driver_id == None,  # noqa: E711
                Order.order_kind != OrderKind.TTN_L,
            ).with_for_update()
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена или уже занята другим водителем")

    order.driver_id = actor.id
    order.status = OrderStatus.ACCEPTED
    await db.flush()

    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=OrderStatus.NEW,
        to_status=OrderStatus.ACCEPTED,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка взята водителем",
    ))

    result = await db.execute(_with_logs(select(Order).where(Order.id == order.id)))
    order = result.scalar_one()
    await attach_payment_totals_one(db, order)

    # Notify chat_service to create the client↔driver conversation for this order.
    # Fire-and-forget: if chat_service is unavailable, the order is still claimed.
    try:
        _settings = _get_settings()
        async with httpx.AsyncClient(timeout=5.0) as http:
            await http.post(
                f"{_settings.chat_service_url}/internal/conversations/ensure-client-driver",
                json={
                    "order_id": str(order.id),
                    "client_id": str(order.client_id),
                    "driver_id": str(order.driver_id),
                    "driver_name": "",
                    "order_number": order.order_number,
                },
                headers={"X-Internal-Secret": _settings.internal_api_secret},
            )
    except Exception as exc:
        log.warning("claim_order: chat ensure_client_driver failed for order %s: %s", order.id, exc)

    await publish_order_event({
        "event": "order_status",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": str(order.driver_id) if order.driver_id else None,
        "status": order.status.value,
        "title": f"Заявка №{order.order_number} принята",
        "body": "Водитель принял вашу заявку",
    })

    await attach_buyer_name_one(order)
    return order


async def ack_changes(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser,
) -> Order:
    """Водитель подтверждает, что увидел изменения в заявке."""
    if actor.role != ROLE_DRIVER:
        raise ForbiddenError("Подтвердить изменения может только водитель")

    order = await get_order(db, order_id, actor)
    order.pending_driver_ack = False
    order.pending_changed_fields = None
    await db.flush()

    result = await db.execute(_with_logs(select(Order).where(Order.id == order.id)))
    order = result.scalar_one()
    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


async def reschedule_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: RescheduleRequest,
    actor: TokenUser,
) -> Order:
    """Перенос заявки: смена desired_date и/или driver_id.

    Доступно всем ролям (клиент — только свою; staff — любую; водитель — назначенную ему).
    Перенос принятой заявки (ACCEPTED) → pending_driver_ack=true + уведомление водителю.
    """
    order = await get_order(db, order_id, actor)

    if data.desired_date is None and data.driver_id is None:
        raise ValidationError("Укажите новую дату или нового водителя для переноса")

    was_accepted = order.status == OrderStatus.ACCEPTED
    changed = False
    changed_keys: list[str] = []

    if data.desired_date is not None:
        order.desired_date = data.desired_date
        changed = True
        changed_keys.append("desired_date")

    if data.driver_id is not None:
        # Только staff может менять водителя
        if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
            raise ForbiddenError("Только менеджер или администратор может переназначить водителя")
        order.driver_id = data.driver_id
        changed = True
        changed_keys.append("driver")

    # Перенос самим водителем подтверждения не требует (правки 2026-06-11);
    # изменения клиента/менеджера водитель подтверждает кнопкой.
    if was_accepted and changed and actor.role != ROLE_DRIVER:
        order.pending_driver_ack = True
        merged = list(order.pending_changed_fields or [])
        for k in changed_keys:
            if k not in merged:
                merged.append(k)
        order.pending_changed_fields = merged

    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=order.status,
        to_status=order.status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка перенесена",
    ))
    await db.flush()

    # Уведомление водителю
    if order.driver_id:
        await publish_order_event({
            "event": "order_rescheduled",
            "order_id": str(order.id),
            "client_id": str(order.client_id),
            "manager_id": str(order.manager_id) if order.manager_id else None,
            "driver_id": str(order.driver_id),
            "status": order.status.value,
            "title": f"Заявка №{order.order_number} перенесена",
            "body": "Дата или водитель заявки изменены",
        })

    result = await db.execute(_with_logs(select(Order).where(Order.id == order.id)))
    order = result.scalar_one()
    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


async def transition_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: OrderStatusTransitionRequest,
    actor: TokenUser,
) -> Order:
    order = await get_order(db, order_id, actor, lock=True)

    validate_transition(order.status, data.to_status, actor.role)

    # ACCEPTED→DELIVERED: водитель обязан указать номер ТТН
    if data.to_status == OrderStatus.DELIVERED:
        if actor.role == ROLE_DRIVER:
            if not order.driver_id or order.driver_id != actor.id:
                raise StatusTransitionError("Сначала возьмите заявку через кнопку «Взять»")
        # Номер ТТН присваивается автоматически (сквозная нумерация ТТН-{год}-{N}).
        # Ручной ввод сохранён для обратной совместимости (ttn_l / ручная коррекция).
        ttn = (data.ttn_number or "").strip()
        if not ttn:
            ttn = await generate_ttn_number(db)
        order.ttn_number = ttn

        # Фиксируем доставленный объём: фактический из формы водителя
        # («сколько отгрузил», правки 2026-06-11) или заказанный по умолчанию.
        order.volume_delivered = (
            float(data.volume_delivered)
            if data.volume_delivered is not None
            else float(order.volume_requested)
        )

        # Пересчитываем final_amount по фактическому объёму (+ стоимость доставки)
        ctx = await get_client_context(order.client_id, order.organization_id)
        recalc = await compute_expected_amount(
            db, order.fuel_type, float(order.volume_delivered), ctx.tariff_id, ctx.client_type,
            ctx.fuel_coefficient,
        )
        if recalc is not None:
            order.final_amount = recalc + (order.delivery_cost or 0)

    if data.to_status == OrderStatus.CANCELLED:
        if data.rejection_reason:
            order.rejection_reason = data.rejection_reason

    prev_status = order.status
    order.status = data.to_status

    # Согласование крупной заявки менеджером (правки 2026-06-11): при одобрении
    # выставляем единый счёт — заказчик подтвердил «выставляется счёт».
    # Ошибка генерации не блокирует согласование (менеджер выставит вручную).
    if prev_status == OrderStatus.AWAITING_MANAGER and data.to_status == OrderStatus.NEW:
        try:
            async with db.begin_nested():
                await document_service.regenerate_invoice(db, order, actor)
        except Exception as exc:
            log.warning("Auto-invoice on approval failed for order %s: %s", order.id, exc)

    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=prev_status,
        to_status=data.to_status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment=data.comment,
    ))
    await db.flush()

    # Авто-генерация документов при доставке
    # ttn_l заявки не генерят счета (Д4 полностью закроет это; здесь предотвращаем
    # генерацию invoice_final для внутренних ТТН-Л)
    if data.to_status == OrderStatus.DELIVERED and order.order_kind != OrderKind.TTN_L:
        # Порог 3000 л (Д4): крупные заявки финальный счёт не выставляют
        # автоматически — менеджеру уходит уведомление для ручного выставления.
        delivered_volume = float(order.volume_delivered or order.volume_requested)
        if delivered_volume >= LARGE_VOLUME_THRESHOLD_L:
            try:
                await _notify_large_volume(order)
            except Exception as exc:
                log.warning("Large-volume notify failed for order %s: %s", order.id, exc)
        else:
            # Единый счёт: перевыпускаем с фактическим объёмом (тот же номер).
            try:
                async with db.begin_nested():
                    await document_service.regenerate_invoice(db, order, actor)
            except Exception as exc:
                log.warning("Auto-invoice regen on delivery failed for order %s: %s", order.id, exc)

        # Departure-транзакция в delivery_service (списание топлива со склада)
        try:
            await _auto_record_delivery(order, actor)
        except StatusTransitionError:
            raise
        except Exception as exc:
            log.error("_auto_record_delivery unexpected error for order %s: %s", order.id, exc)
    elif data.to_status == OrderStatus.DELIVERED and order.order_kind == OrderKind.TTN_L:
        # ТТН-Л: только списываем топливо, без счёта
        try:
            await _auto_record_delivery(order, actor)
        except StatusTransitionError:
            raise
        except Exception as exc:
            log.error("_auto_record_delivery (ttn_l) unexpected error for order %s: %s", order.id, exc)

    # Re-fetch to include the new log in the response
    result = await db.execute(
        _with_logs(select(Order).where(Order.id == order.id))
    )
    order = result.scalar_one()

    if prev_status == OrderStatus.AWAITING_MANAGER and order.status == OrderStatus.NEW:
        event_title = f"Заявка №{order.order_number} согласована"
        event_body = "Менеджер согласовал заявку — она передана водителям."
    else:
        event_title = f"Статус заявки №{order.order_number} изменён"
        event_body = f"Новый статус: {order.status.value}"
    await publish_order_event({
        "event": "order_status",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": str(order.driver_id) if order.driver_id else None,
        "status": order.status.value,
        "title": event_title,
        "body": event_body,
    })

    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


async def archive_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser,
) -> None:
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError()

    result = await db.execute(
        _with_logs(select(Order).where(Order.id == order_id, Order.is_archived == False))  # noqa: E712
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена")

    order.is_archived = True
    order.archived_at = datetime.now(timezone.utc)

    # Audit: record who archived the order
    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=order.status,
        to_status=order.status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка архивирована",
    ))
