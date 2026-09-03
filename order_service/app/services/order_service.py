import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal as _Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func, delete as sa_delete
from sqlalchemy.orm import selectinload

import httpx
import jwt as jose_jwt

from app.config import get_settings as _get_settings
from app.models.order import Order, OrderStatus, OrderKind, PaymentType
from app.services import fuel_type_service
from app.models.order_status_log import OrderStatusLog
from app.core.dependencies import TokenUser
from app.core.status_machine import validate_transition
from app.core.media import resolve_media_path
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
from app.services.money import round_order_total, per_liter_with_delivery
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


def _visibility_conditions(
    actor: TokenUser,
    org_ids: list | None = None,
    kind: OrderKind | None = None,
) -> list:
    """Условия видимости заявок по роли — общие для списка и счётчиков.

    Для клиента: свои заявки (client_id) + все заявки его организаций
    (organization_id ∈ org_ids) — member видит весь учёт по юрлицу.

    kind — фильтр вида заявки (физ/юр/ТТН-Л) поверх видимости: сужает выдачу
    для любой роли, прав не расширяет (правки 2026-09-02).
    """
    conditions = [Order.is_archived == False]  # noqa: E712
    if kind is not None:
        conditions.append(Order.order_kind == kind)

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
    *,
    kind: OrderKind | None = None,
) -> dict[str, int]:
    """Количество заявок по каждому статусу в пределах видимости роли.
    Используется для бейджей на вкладках реестра (правка заказчика 2026-06-16)."""
    org_ids = await get_user_organization_ids(actor.id) if actor.role == ROLE_CLIENT else None
    conditions = _visibility_conditions(actor, org_ids, kind)
    result = await db.execute(
        select(Order.status, func.count())
        .where(and_(*conditions))
        .group_by(Order.status)
    )
    return {status.value: count for status, count in result.all()}


async def last_delivery_by_client(
    db: AsyncSession,
    actor: TokenUser,
) -> dict[str, str]:
    """{client_id: ISO-дата последней доставки} — по фактическому моменту перехода
    заявки в DELIVERED (история статусов). База разовых клиентов, правки 2026-07-11."""
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError()
    result = await db.execute(
        select(Order.client_id, func.max(OrderStatusLog.created_at))
        .join(OrderStatusLog, OrderStatusLog.order_id == Order.id)
        .where(OrderStatusLog.to_status == OrderStatus.DELIVERED)
        .group_by(Order.client_id)
    )
    return {str(client_id): dt.isoformat() for client_id, dt in result.all()}


async def list_orders(
    db: AsyncSession,
    actor: TokenUser,
    *,
    status: OrderStatus | None = None,
    driver_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    kind: OrderKind | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Order]:
    org_ids = await get_user_organization_ids(actor.id) if actor.role == ROLE_CLIENT else None
    conditions = _visibility_conditions(actor, org_ids, kind)

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
    is_staff = actor.role in (ROLE_MANAGER, ROLE_ADMIN)

    if is_staff and not data.client_id:
        # Менеджер без выбранного клиента (напр. разовый клиент ещё не создан):
        # у самого менеджера client_profile нет — считаем по default-тарифу физлица.
        from app.services.client_context import ClientContext
        ctx = ClientContext(
            user_id=actor.id, client_type="individual", credit_allowed=False,
            tariff_id=None, credit_limit=None,
        )
    else:
        client_id = data.client_id if (is_staff and data.client_id) else actor.id
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
                    ctx.client_type,
                )
    except Exception as exc:
        log.warning("preview_price: zone resolution failed (non-fatal): %s", exc)

    # Ручная стоимость доставки в форме админа перекрывает зональный расчёт —
    # иначе «Итого» в превью не совпадало с тем, что получится при создании.
    manual_delivery = data.manual_delivery_cost if is_staff else None
    delivery_is_manual = manual_delivery is not None
    if delivery_is_manual:
        delivery_cost = _Decimal(str(manual_delivery))

    fuel_subtotal = bd["fuel_subtotal"]
    if fuel_subtotal is not None:
        # Итог — целые рубли, копейки гасятся в доставке (правки 2026-08-24)
        total, delivery_cost = round_order_total(fuel_subtotal, delivery_cost)
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
        "delivery_is_manual": delivery_is_manual,
        "total": total,
        "price_per_liter_with_delivery": per_liter_with_delivery(total, data.volume),
        "pricing_warning": pricing_warning,
    }


def _normalize_delivery_address(address: str | None, actor: TokenUser) -> str:
    """CRM-37: адрес обязателен только клиенту.

    Сотрудник и водитель оформляют заявку со слов — адрес уточняет менеджер.
    Пустая строка (колонка NOT NULL) означает «адрес уточняется»: зона и
    стоимость доставки останутся пустыми.
    """
    normalized = (address or "").strip()
    if not normalized and actor.role == ROLE_CLIENT:
        raise ValidationError("Укажите адрес доставки")
    return normalized


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

    # Режим «только чаты» (правки 2026-07-14): клиенту заявки запрещены.
    # Менеджер/админ может оформить заявку НА такого клиента — блокируем только самообслуживание.
    if not is_staff and ctx.chats_only:
        raise ForbiddenError("Ваш доступ ограничен чатами — для заказа свяжитесь с менеджером")

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
        # Юрлицо с разрешённым кредитом и без явного выбора типа оплаты работает
        # «в долг» — иначе заявка молча уезжала предоплатой и вставала в «ждём
        # оплату» (правки 2026-09-02). Сервер — источник истины, фронт лишь отражает.
        if "payment_type" not in data.model_fields_set and ctx.credit_allowed:
            data.payment_type = PaymentType.DEBT
        # Validate payment_type against role × client_type × credit_allowed matrix
        validate_payment_type(
            data.payment_type,
            actor_role=actor.role,
            client_type=ctx.client_type,
            credit_allowed=ctx.credit_allowed,
        )

    data.delivery_address = _normalize_delivery_address(data.delivery_address, actor)

    # Дата доставки не может быть в прошлом. Сравниваем календарные дни,
    # а не моменты времени: заявка «на сегодня» валидна весь день, даже если
    # присланный timestamp (полдень UTC от фронта) уже позади текущего момента.
    if data.desired_date:
        desired_utc = data.desired_date if data.desired_date.tzinfo else data.desired_date.replace(tzinfo=timezone.utc)
        if desired_utc.date() < datetime.now(timezone.utc).date():
            raise ValidationError("Желаемая дата доставки не может быть в прошлом")

    # Валидация вида топлива по каталогу (hard-fail: неизвестный/неактивный код → 422)
    await fuel_type_service.validate_active(db, data.fuel_type)

    # Проверка остатка на складе убрана (правки 2026-07-14): продажа разрешена
    # даже при нулевом/отрицательном остатке — учёт ведётся по ёмкостям.

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

    # Без адреса (CRM-37) зону не определяем даже при случайно пришедших
    # координатах: считать доставку не к чему — её уточнит менеджер.
    if data.delivery_address and delivery_lat is not None and delivery_lon is not None:
        try:
            zone_info = await resolve_zone(delivery_lat, delivery_lon)
            if zone_info:
                resolved_zone_id = uuid.UUID(zone_info["zone_id"])
                resolved_zone_name = zone_info["name"]
                if zone_info.get("delivery_price") is not None:
                    # Фиксированная цена доставки по зоне — тариф не нужен
                    delivery_cost = compute_zone_delivery_cost(
                        zone_info, None, data.volume_requested,
                        ctx.delivery_coefficient, ctx.client_type,
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
                            ctx.client_type,
                        )
        except Exception as exc:
            log.warning("Zone pricing failed for order (non-fatal): %s", exc)

    # Ручная стоимость доставки (правки 2026-07-25, только staff):
    # перекрывает зональный автосчёт — админ вводит цену прямо в форме.
    delivery_is_manual = is_staff and data.manual_delivery_cost is not None
    if delivery_is_manual:
        delivery_cost = data.manual_delivery_cost

    # Итог = топливо + доставка, округлённый до целого рубля; копеечная поправка
    # ложится на доставку, чтобы строки счёта сходились с итогом (правки 2026-08-24).
    # Если тариф не настроен (топливная часть не рассчитана) — итог остаётся NULL:
    # выдавать одну лишь доставку за сумму заявки нельзя, менеджер проставит руками.
    if expected_amount is not None:
        expected_amount, delivery_cost = round_order_total(expected_amount, delivery_cost)
    elif delivery_cost is not None:
        log.warning(
            "Order create: тариф не рассчитан, итог оставлен пустым (доставка %s)",
            delivery_cost,
        )

    # Согласование заявок (правки 2026-06-16):
    # - Физ лица: ВСЕ заявки клиента уходят на согласование менеджера.
    # - Юр лица: только строго > 3000 л.
    # - Плюс (правки 2026-07-25): ЛЮБАЯ клиентская заявка, где стоимость
    #   доставки не рассчиталась автоматически (нет зоны/координат) — менеджер
    #   должен проставить цену руками до запуска в работу.
    # Водители заявку на согласовании не видят и не могут взять.
    # Заявки, созданные менеджером/админом, согласования не требуют.
    needs_approval = (
        not is_staff
        and order_kind != OrderKind.TTN_L
        and (
            ctx.client_type == "individual"
            or float(data.volume_requested) > LARGE_VOLUME_THRESHOLD_L
            or delivery_cost is None
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
        delivery_cost_is_manual=bool(delivery_is_manual),
        # Only manager/admin may mark an order as debt (allow_delivery_unpaid)
        allow_delivery_unpaid=data.allow_delivery_unpaid if is_staff else False,
        # «Ждём оплату» при создании (правки 2026-07-25, только staff)
        shipment_override="hold" if (is_staff and data.shipment_hold) else None,
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
                invoice_doc = await document_service.generate_invoice(db, order, actor)
            except Exception as exc:
                log.warning("Auto-invoice failed for order %s: %s", order.id, exc)
                invoice_doc = None

            # Юрлицо ≤3000 л: счёт сразу уходит клиенту в чат и на email
            # (правка заказчика 2026-06-24). Best-effort — ошибка отправки
            # никогда не должна срывать создание заявки. Физлица — без авто-отправки.
            if invoice_doc is not None and ctx.client_type == "company":
                try:
                    await document_service.send_document_to_chat(
                        db, order, invoice_doc, actor.token,
                    )
                except Exception as exc:
                    log.warning("Auto-send invoice to chat failed for order %s: %s", order.id, exc)
                try:
                    await document_service.send_document_by_email(db, order, invoice_doc)
                except Exception as exc:
                    log.warning("Auto-send invoice email failed for order %s: %s", order.id, exc)

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
# organization_id — смена заказчика (правка 2026-06-24, скрин 6): клиент может
# переключить заявку на одну из своих организаций или на физлицо (null).
_CLIENT_EDITABLE = {"fuel_type", "volume_requested", "delivery_address", "desired_date",
                    "client_comment", "contact_person_name", "contact_person_phone",
                    "organization_id"}
# Поля, которые водитель может править в назначенной ему заявке
_DRIVER_EDITABLE = {"fuel_type", "volume_requested", "delivery_address", "desired_date"}
# Статусы, в которых клиент/водитель ещё могут править заявку
_EDITABLE_STATUSES = {OrderStatus.NEW, OrderStatus.AWAITING_MANAGER, OrderStatus.ACCEPTED}
# Закрытые статусы (CRM-39): заявка уже отработана — правит только админ,
# и только «бумажные» поля: объём и топливо после доставки не меняются
# (по ним уже выписаны ТТН, счёт и списан склад).
_CLOSED_STATUSES = {
    OrderStatus.DELIVERED: ("Доставленную", "доставленной"),
    OrderStatus.CANCELLED: ("Отменённую", "отменённой"),
}
_FROZEN_IN_CLOSED = {"fuel_type", "volume_requested"}


def _check_closed_order_edit(order: Order, actor: TokenUser, requested_fields: set[str]) -> None:
    """CRM-39: правка заявки в закрытом статусе (доставлена/отменена).

    Менеджеру закрыто совсем, админу — всё, кроме объёма и вида топлива:
    по ним уже выписаны ТТН со счётом и списан склад.
    """
    if order.status not in _CLOSED_STATUSES:
        return
    accusative, genitive = _CLOSED_STATUSES[order.status]
    if actor.role != ROLE_ADMIN:
        raise ForbiddenError(f"{accusative} заявку правит только администратор")
    if requested_fields & _FROZEN_IN_CLOSED:
        raise ValidationError(f"Объём и вид топлива {genitive} заявки не меняются")


async def _fuel_subtotal_for(db: AsyncSession, order: Order, ctx, volume: float | None = None):
    """Топливная часть суммы заявки по тарифу клиента (без доставки)."""
    vol = float(order.volume_requested) if volume is None else float(volume)
    return await compute_expected_amount(
        db, order.fuel_type, vol, ctx.tariff_id, ctx.client_type, ctx.fuel_coefficient,
    )


async def _recompute_expected_amount(db: AsyncSession, order: Order) -> None:
    """Пересчитать expected_amount и delivery_cost после смены топлива/объёма.

    Fail-open по сервисам: при недоступности auth/delivery суммы остаются прежними.
    Но если тариф не нашёлся — итог честно сбрасывается в NULL (правки 2026-08-24):
    показать прочерк лучше, чем оставить сумму от прежнего объёма/топлива.
    Ручную стоимость доставки (delivery_cost_is_manual) зональной НЕ перетираем.
    """
    try:
        ctx = await get_client_context(order.client_id, order.organization_id)
        expected = await _fuel_subtotal_for(db, order, ctx)
        delivery_cost = order.delivery_cost
        if (
            not order.delivery_cost_is_manual
            and order.delivery_lat is not None
            and order.delivery_lon is not None
        ):
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
                    ctx.client_type,
                )
                if recalc_delivery is not None:
                    delivery_cost = recalc_delivery
                    order.delivery_cost = recalc_delivery
        if expected is None:
            log.warning(
                "recompute_expected_amount: тариф не найден для заявки %s "
                "(fuel=%s) — итог сброшен в NULL", order.id, order.fuel_type,
            )
            order.expected_amount = None
            return
        total, adjusted_delivery = round_order_total(expected, delivery_cost)
        order.expected_amount = total
        if adjusted_delivery is not None:
            order.delivery_cost = adjusted_delivery
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
    # organization_id — особый случай: null — это валидное намеренное значение
    # (переключение заказчика на физлицо), exclude_none его бы скрыл, поэтому
    # детектируем "поле передано" через model_fields_set отдельно.
    organization_id_requested = "organization_id" in data.model_fields_set
    if organization_id_requested:
        requested_fields.add("organization_id")

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
    else:
        _check_closed_order_edit(order, actor, requested_fields)

    # Минимальный объём — только клиентам и водителям; менеджер/админ правит на
    # любой объём (правка заказчика 2026-07-16), как и при создании заявки.
    if (
        not is_staff
        and data.volume_requested is not None
        and data.volume_requested < MIN_VOLUME_L
    ):
        raise ValidationError(f"Минимальный объём заказа — {MIN_VOLUME_L} литров")
    if data.fuel_type is not None:
        await fuel_type_service.validate_active(db, data.fuel_type)
    if data.desired_date is not None:
        # Сравнение по календарным дням — «на сегодня» валидно весь день (см. создание заявки)
        desired_utc = (data.desired_date if data.desired_date.tzinfo
                       else data.desired_date.replace(tzinfo=timezone.utc))
        if desired_utc.date() < datetime.now(timezone.utc).date():
            raise ValidationError("Желаемая дата доставки не может быть в прошлом")

    # Смена заказчика (правка 2026-06-24): organization_id=<uuid> — переключить на
    # организацию-юрлицо; organization_id=null — переключить на физлицо. Допустимо
    # только если новая организация — та, в которой состоит клиент заявки (та же
    # проверка членства, что и при создании заявки через get_client_context).
    # Существующие документы/договор по заявке не трогаем — это ручное действие.
    if organization_id_requested and data.organization_id != order.organization_id:
        if data.organization_id is not None:
            member_org_ids = await get_user_organization_ids(order.client_id)
            if data.organization_id not in member_org_ids:
                raise ValidationError(
                    "Указанная организация не найдена среди организаций клиента заявки"
                )

    # Track if we need to set pending_driver_ack
    was_accepted = order.status == OrderStatus.ACCEPTED
    changed = False
    # Ключи изменённых полей для индикации «что поменялось» (правки 2026-06-11)
    changed_keys: list[str] = []

    # Правка комментария сбрасывает подтверждение водителя (правки 2026-08-24):
    # у водителя снова загорается янтарный «!» и кнопка «Комментарий увидел».
    def _reset_comment_ack(old: str | None, new: str | None) -> None:
        if new and (new or "").strip() != (old or "").strip():
            order.driver_comment_ack_at = None

    if data.manager_comment is not None:
        _reset_comment_ack(order.manager_comment, data.manager_comment)
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
        _reset_comment_ack(order.client_comment, data.client_comment)
        order.client_comment = data.client_comment
        changed = True
        changed_keys.append("comment")
    if data.contact_person_name is not None:
        order.contact_person_name = data.contact_person_name
        changed = True
    if data.contact_person_phone is not None:
        order.contact_person_phone = data.contact_person_phone
        changed = True
    if organization_id_requested and data.organization_id != order.organization_id:
        order.organization_id = data.organization_id
        changed = True
        changed_keys.append("organization")
    _final_amount_touched = False
    if data.delivery_cost is not None:
        # Перекладываем долю доставки в суммы заявки: топливная часть
        # (сумма − старый delivery_cost) сохраняется, доставка заменяется.
        # Ручной ввод помечаем флагом — пересчёт по объёму его не перетрёт.
        order.delivery_cost_is_manual = True
        old_delivery = order.delivery_cost or _Decimal("0")

        fuel_expected = None
        if order.expected_amount is not None:
            fuel_expected = order.expected_amount - old_delivery
        else:
            # Итог не рассчитан (заявка ушла на согласование из-за нерассчитанной
            # доставки) — восстанавливаем топливную часть по тарифу клиента,
            # иначе ввод цены доставки не давал итога вовсе (баг 2026-08-24).
            try:
                _ctx = await get_client_context(order.client_id, order.organization_id)
                fuel_expected = await _fuel_subtotal_for(db, order, _ctx)
            except Exception as exc:
                log.warning(
                    "delivery_cost edit: не удалось пересчитать топливо по тарифу "
                    "для заявки %s: %s", order.id, exc,
                )
            if fuel_expected is None:
                log.warning(
                    "delivery_cost edit: тариф не найден для заявки %s — итог "
                    "остаётся пустым", order.id,
                )

        fuel_final = (
            order.final_amount - old_delivery if order.final_amount is not None else None
        )

        # Копеечную поправку доставки считаем от «главной» суммы: фактическая
        # важнее ожидаемой (от неё считаются долг и счёт).
        base_for_adjust = fuel_final if fuel_final is not None else fuel_expected
        if base_for_adjust is not None:
            _t, adjusted_delivery = round_order_total(base_for_adjust, data.delivery_cost)
            order.delivery_cost = adjusted_delivery
        else:
            order.delivery_cost = data.delivery_cost

        if data.expected_amount is None and fuel_expected is not None:
            order.expected_amount = round_order_total(fuel_expected, order.delivery_cost)[0]
        # Доставленная заявка: долг и счёт считаются от final_amount — его тоже
        # надо подвинуть на дельту доставки (баг 2026-08-24).
        if data.final_amount is None and fuel_final is not None:
            order.final_amount = round_order_total(fuel_final, order.delivery_cost)[0]
            _final_amount_touched = True
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
    elif _final_amount_touched:
        # final_amount сдвинулся из-за правки стоимости доставки — статус оплаты
        # (долг/переплата) считается от него, поэтому пересчитываем и здесь.
        await recompute_and_save(db, order)

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


async def set_shipment_override(
    db: AsyncSession,
    order_id: uuid.UUID,
    mode: str,
    actor: TokenUser,
) -> Order:
    """Перекрытие отгрузки (правки 2026-07-25): allow / hold / auto (сброс).

    Только менеджер/админ. Пишется в status_log — видно, кто и когда
    разрешил отгрузку без оплаты или поставил заявку на ожидание.
    """
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Управлять отгрузкой может только менеджер или администратор")

    order = await get_order(db, order_id, actor)
    order.shipment_override = None if mode == "auto" else mode
    label = {
        "allow": "отгрузка разрешена вручную",
        "hold": "ждём оплату (вручную)",
        "auto": "отгрузка: автоматический режим",
    }[mode]
    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=order.status,
        to_status=order.status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment=label,
    ))
    await db.flush()

    result = await db.execute(_with_logs(select(Order).where(Order.id == order.id)))
    order = result.scalar_one()
    await attach_payment_totals_one(db, order)
    await attach_buyer_name_one(order)
    return order


async def ack_comment(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser,
) -> Order:
    """Водитель подтверждает, что увидел комментарий к заявке (2026-07-25)."""
    if actor.role != ROLE_DRIVER:
        raise ForbiddenError("Подтвердить комментарий может только водитель")

    order = await get_order(db, order_id, actor)
    order.driver_comment_ack_at = datetime.now(timezone.utc)
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
    idempotency_key: str | None = None,
) -> Order:
    # ── Idempotency gate (mobile offline-outbox) ───────────────────────────
    # Insert-first: атомарно «занимаем» ключ. Параллельный дубликат блокируется
    # на unique-индексе до нашего commit/rollback, затем видит строку и
    # возвращает текущее состояние заказа — без повторного перехода статуса,
    # повторного списания топлива и повторной публикации события.
    owns_idem_slot = False
    if idempotency_key is not None:
        from app.models.idempotency_key import IdempotencyKey
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        claim = await db.execute(
            pg_insert(IdempotencyKey)
            .values(key=idempotency_key, operation="order_transition", order_id=order_id)
            .on_conflict_do_nothing(index_elements=["key"])
            .returning(IdempotencyKey.key)
        )
        owns_idem_slot = claim.scalar_one_or_none() is not None
        if not owns_idem_slot:
            # Ключ уже обработан — возвращаем текущее состояние заказа
            cached = await get_order(db, order_id, actor)
            return cached
    # ── End idempotency gate ───────────────────────────────────────────────

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

        # Итог по факту (правки заказчицы 2026-08-24, скрины ю187/ю194):
        # 1) объём НЕ изменился → факт = ожидаемому, никакого пересчёта.
        #    Раньше пересчитывали по ТЕКУЩЕМУ тарифу — если цена для клиента
        #    менялась после создания заявки, «Факт» расходился с «Ожидалось»
        #    и со счётом при том же литраже (600 л: 58 270 → 52 270).
        # 2) объём изменился → цена за литр берётся из УСЛОВИЙ ЗАЯВКИ:
        #    (expected − доставка) / заказанный объём. Текущий прайс — только
        #    fallback, когда ожидаемой суммы вообще нет (тариф не был настроен).
        vol_req = float(order.volume_requested or 0)
        vol_fact = float(order.volume_delivered)
        if order.expected_amount is not None and abs(vol_fact - vol_req) < 1e-9:
            order.final_amount = order.expected_amount
        else:
            recalc = None
            if order.expected_amount is not None and vol_req > 0:
                delivery_dec = _Decimal(str(order.delivery_cost)) if order.delivery_cost is not None else _Decimal("0")
                fuel_expected = _Decimal(str(order.expected_amount)) - delivery_dec
                recalc = fuel_expected * _Decimal(str(vol_fact)) / _Decimal(str(vol_req))
            else:
                ctx = await get_client_context(order.client_id, order.organization_id)
                recalc = await compute_expected_amount(
                    db, order.fuel_type, vol_fact, ctx.tariff_id, ctx.client_type,
                    ctx.fuel_coefficient,
                )
            if recalc is not None:
                # Итог целыми рублями, копейки — в строку доставки (правки 2026-08-24)
                total, adjusted_delivery = round_order_total(recalc, order.delivery_cost)
                order.final_amount = total
                if adjusted_delivery is not None:
                    order.delivery_cost = adjusted_delivery
            else:
                log.warning(
                    "DELIVERED: тариф не найден для заявки %s — final_amount не пересчитан",
                    order.id,
                )

    if data.to_status == OrderStatus.CANCELLED:
        if data.rejection_reason:
            order.rejection_reason = data.rejection_reason

    prev_status = order.status
    order.status = data.to_status
    invoice_error: str | None = None

    # Согласование крупной заявки менеджером (правки 2026-06-11): при одобрении
    # выставляем единый счёт — заказчик подтвердил «выставляется счёт».
    # Ошибка генерации не блокирует согласование (менеджер выставит вручную).
    if prev_status == OrderStatus.AWAITING_MANAGER and data.to_status == OrderStatus.NEW:
        # Перед выпуском счёта пересчитываем итог: на согласование заявка могла
        # уйти именно из-за нерассчитанной суммы/доставки (правки 2026-08-24).
        if order.expected_amount is None:
            await _recompute_expected_amount(db, order)
        try:
            async with db.begin_nested():
                await document_service.regenerate_invoice(db, order, actor)
        except ValidationError as exc:
            # Типовая причина — не рассчитана сумма заявки (нет тарифа/доставки).
            # Раньше это молча уходило в log.warning, и менеджер думал, что счёт
            # выставлен. Согласование не откатываем, но говорим об этом явно.
            log.warning("Auto-invoice on approval failed for order %s: %s", order.id, exc)
            invoice_error = str(exc)
        except Exception as exc:
            log.error("Auto-invoice on approval failed for order %s: %s", order.id, exc)
            invoice_error = "Счёт не выпущен — повторите выставление вручную."

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
    # Предупреждение о невыпущенном счёте едет в ответе — переход состоялся,
    # но менеджер должен узнать, что счёт выставить не удалось.
    order.invoice_warning = invoice_error

    # Строка идемпотентности с order_id уже записана gate'ом в начале функции —
    # повторная вставка не нужна.
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


def _remove_document_files(file_paths: list[str]) -> None:
    """Удалить PDF-файлы документов с диска. Ошибки логируем, но не падаем:
    строки в БД уже удалены, осиротевший файл менее вреден, чем 500 на удалении."""
    from app.services.document_service import MEDIA_ROOT

    for rel_path in file_paths:
        try:
            path = resolve_media_path(MEDIA_ROOT, rel_path)
            path.unlink(missing_ok=True)
        except Exception:
            log.warning("Не удалось удалить файл документа %s", rel_path, exc_info=True)


async def hard_delete_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser,
) -> dict:
    """Полное удаление заявки со всеми связанными данными (только админ).

    Архивирование (archive_order) остаётся мягким удалением; это — необратимое.
    Каскад в order_service: документы (+ PDF с диска), платежи, лог статусов,
    ключи идемпотентности, сама заявка. Счётчики номеров заявок и ТТН НЕ трогаем —
    номера не переиспользуются.

    Данные в других сервисах (рейсы и складские проводки delivery_service, чат
    заявки, уведомления) удаляются подписчиками события `order_deleted`
    в канале events:orders.
    """
    from app.models.document import Document
    from app.models.idempotency_key import IdempotencyKey
    from app.models.payment import Payment

    if actor.role != ROLE_ADMIN:
        raise ForbiddenError("Полное удаление заявки доступно только администратору")

    # Архивные заявки тоже удаляем — удаление доступно в любом статусе.
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена")

    order_number = order.order_number
    ttn_number = order.ttn_number
    status_value = order.status.value
    client_id = str(order.client_id) if order.client_id else None
    driver_id = str(order.driver_id) if order.driver_id else None
    # Сколько литров вернётся на склад: фактически доставленный объём.
    stock_restored_l = (
        float(order.volume_delivered) if order.volume_delivered is not None else None
    )

    doc_paths = [
        p for p in (
            await db.execute(
                select(Document.file_path).where(Document.order_id == order_id)
            )
        ).scalars().all()
        if p
    ]

    await db.execute(sa_delete(Document).where(Document.order_id == order_id))
    await db.execute(sa_delete(Payment).where(Payment.order_id == order_id))
    await db.execute(sa_delete(OrderStatusLog).where(OrderStatusLog.order_id == order_id))
    await db.execute(sa_delete(IdempotencyKey).where(IdempotencyKey.order_id == order_id))
    await db.execute(sa_delete(Order).where(Order.id == order_id))
    await db.commit()

    _remove_document_files(doc_paths)

    log.warning(
        "action=order.hard_deleted order_id=%s order_number=%s actor_id=%s status=%s",
        order_id, order_number, actor.id, status_value,
    )

    # Событие — только после успешного commit: подписчики (delivery/chat/
    # notification) чистят свои данные и откатить их вместе с нами нельзя.
    await publish_order_event({
        "event": "order_deleted",
        "order_id": str(order_id),
        "order_number": order_number,
        "ttn_number": ttn_number,
        "actor_id": str(actor.id),
        "client_id": client_id,
        "driver_id": driver_id,
    })

    return {
        "deleted": True,
        "order_number": order_number,
        "stock_restored_l": stock_restored_l,
    }
