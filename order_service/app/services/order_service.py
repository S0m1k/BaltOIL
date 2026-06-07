import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from sqlalchemy.orm import selectinload

import httpx
from jose import jwt as jose_jwt

from app.config import get_settings as _get_settings
from app.models.order import Order, OrderStatus, OrderKind, PaymentType
from app.services import fuel_type_service
from app.models.order_status_log import OrderStatusLog
from app.core.dependencies import TokenUser
from app.core.status_machine import validate_transition
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError, StatusTransitionError
from app.schemas.order import OrderCreateRequest, OrderUpdateRequest, OrderStatusTransitionRequest, RescheduleRequest
from app.services.order_number import generate_order_number
from app.services.payment_service import (
    recompute_and_save,
    attach_payment_totals,
    attach_payment_totals_one,
)
from app.services import document_service
from app.services import contract_service
from app.services.client_context import get_client_context
from app.services.payment_type_rules import validate_payment_type
from app.services.pricing_service import compute_expected_amount, get_tariff, get_default_tariff
from app.services.zone_pricing import resolve_zone
from app.core.events import publish_order_event

log = logging.getLogger(__name__)

# Порог объёма (л): при >= этого значения счёт не выставляется автоматически —
# менеджер получает уведомление и выставляет вручную (Д4, решение 2026-06-05).
LARGE_VOLUME_THRESHOLD_L = 3000


async def _notify_large_volume(order: Order) -> None:
    """Уведомить менеджеров: заявка >= порога, счёт нужно выставить вручную."""
    await publish_order_event({
        "event": "order_large_volume",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": None,
        "status": order.status.value,
        "title": f"Заявка №{order.order_number}: объём ≥ 3000 л",
        "body": "Счёт не выставлен автоматически — выставьте вручную.",
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
        log.error("_auto_record_delivery failed for order %s: %s", order.id, exc)
        raise StatusTransitionError(
            "Не удалось зафиксировать доставку: сервис доставки недоступен. Попробуйте позже."
        )


ROLE_CLIENT = "client"
ROLE_DRIVER = "driver"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"


def _with_logs(query):
    return query.options(selectinload(Order.status_logs))


async def get_order(db: AsyncSession, order_id: uuid.UUID, actor: TokenUser) -> Order:
    result = await db.execute(
        _with_logs(
            select(Order).where(Order.id == order_id, Order.is_archived == False)  # noqa: E712
        )
    )
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
    return order


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
    conditions = [Order.is_archived == False]  # noqa: E712

    if actor.role == ROLE_CLIENT:
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
    return orders


async def create_order(
    db: AsyncSession,
    data: OrderCreateRequest,
    actor: TokenUser,
) -> Order:
    is_staff = actor.role in (ROLE_MANAGER, ROLE_ADMIN)

    if not is_staff and actor.role != ROLE_CLIENT:
        raise ForbiddenError("Создание заявок доступно клиентам, менеджерам и администраторам")

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

    # Fetch client context (client_type, credit_allowed, tariff_id) from auth_service.
    # Fails with 503 if auth_service is unreachable — we never silently skip this check.
    ctx = await get_client_context(client_id)

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
        db, data.fuel_type, data.volume_requested, ctx.tariff_id, ctx.client_type
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
                coef = zone_info["cost_coefficient"]
                # Fetch tariff to read base_delivery_cost
                from decimal import Decimal as _Decimal
                tariff = (
                    await get_tariff(db, ctx.tariff_id)
                    if ctx.tariff_id
                    else await get_default_tariff(db, ctx.client_type)
                )
                if tariff is not None and tariff.base_delivery_cost:
                    delivery_cost = (_Decimal(str(tariff.base_delivery_cost)) * _Decimal(str(coef))).quantize(_Decimal("0.01"))
                    if expected_amount is not None:
                        expected_amount = expected_amount + delivery_cost
                    # If expected_amount was None, set it to just the delivery cost
                    else:
                        expected_amount = delivery_cost
        except Exception as exc:
            log.warning("Zone pricing failed for order (non-fatal): %s", exc)

    order = Order(
        order_number=order_number,
        order_kind=order_kind,
        client_id=client_id,
        manager_id=actor.id if is_staff else None,
        driver_id=data.driver_id if is_staff else None,
        fuel_type=data.fuel_type,
        volume_requested=data.volume_requested,
        delivery_address=data.delivery_address,
        desired_date=data.desired_date,
        payment_type=data.payment_type,
        expected_amount=expected_amount,
        client_comment=data.client_comment,
        manager_comment=data.manager_comment if is_staff else None,
        status=OrderStatus.NEW,
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
    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=None,
        to_status=OrderStatus.NEW,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка создана" if not is_staff else "Заявка создана менеджером",
    ))

    await db.flush()

    # Auto-document: предварительный счёт при создании любой не-ttn_l заявки.
    # Порог 3000 л (Д4): крупные заявки не выставляются автоматически — менеджер
    # получает уведомление и выставляет счёт вручную. ttn_l счетов не имеет.
    if order.order_kind != OrderKind.TTN_L:
        if float(order.volume_requested) >= LARGE_VOLUME_THRESHOLD_L:
            try:
                await _notify_large_volume(order)
            except Exception as exc:
                log.warning("Large-volume notify failed for order %s: %s", order.id, exc)
        else:
            try:
                await document_service.generate_invoice_preliminary(db, order, actor)
            except Exception as exc:
                log.warning("Auto-invoice_preliminary failed for order %s: %s", order.id, exc)

    # Auto-contract: для клиента-юрлица без активного договора формируем договор
    # поставки. Не блокируем заявку — любая ошибка только логируется.
    # Физлица и ttn_l пропускаются тихо.
    if ctx.client_type == "company" and order.order_kind != OrderKind.TTN_L:
        try:
            existing = await contract_service.get_active_contract(db, client_id)
            if existing is None:
                await contract_service.create_contract(db, client_id, actor)
        except Exception as exc:
            log.warning("Auto-contract failed for client %s (order %s): %s",
                        client_id, order.id, exc)

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
    return order


async def update_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: OrderUpdateRequest,
    actor: TokenUser,
) -> Order:
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Редактирование заявок доступно менеджеру и администратору")

    order = await get_order(db, order_id, actor)

    # Track if we need to set pending_driver_ack
    was_accepted = order.status == OrderStatus.ACCEPTED
    changed = False

    if data.manager_comment is not None:
        order.manager_comment = data.manager_comment
        changed = True
    if data.desired_date is not None:
        order.desired_date = data.desired_date
        changed = True
    if data.driver_id is not None:
        order.driver_id = data.driver_id
        changed = True
    if data.expected_amount is not None:
        order.expected_amount = data.expected_amount
        changed = True
    if data.trade_credit_contract_signed is not None:
        order.trade_credit_contract_signed = data.trade_credit_contract_signed
        changed = True
    if data.delivery_address is not None:
        order.delivery_address = data.delivery_address
        changed = True
    if data.fuel_type is not None:
        order.fuel_type = data.fuel_type
        changed = True
    if data.volume_requested is not None:
        order.volume_requested = data.volume_requested
        changed = True
    if data.payment_type is not None:
        order.payment_type = data.payment_type
        changed = True
    if data.client_comment is not None:
        order.client_comment = data.client_comment
        changed = True
    if data.delivery_cost is not None:
        order.delivery_cost = data.delivery_cost
        changed = True
    if data.allow_delivery_unpaid is not None:
        order.allow_delivery_unpaid = data.allow_delivery_unpaid
        changed = True

    # final_amount меняет цель — пересчитываем payment_status
    if data.final_amount is not None:
        order.final_amount = data.final_amount
        await recompute_and_save(db, order)
        changed = True

    # Если заявка была в ACCEPTED и что-то изменилось — водитель должен подтвердить
    if was_accepted and changed:
        order.pending_driver_ack = True

    # Re-fetch с eager-загрузкой status_logs (как в create/transition): иначе после
    # flush server-side updated_at (onupdate) протухает и сериализация ответа лезет
    # в lazy-load вне async-контекста → MissingGreenlet → 500.
    await db.flush()
    result = await db.execute(
        _with_logs(select(Order).where(Order.id == order_id))
    )
    order = result.scalar_one()

    await attach_payment_totals_one(db, order)
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
    await db.flush()

    result = await db.execute(_with_logs(select(Order).where(Order.id == order.id)))
    order = result.scalar_one()
    await attach_payment_totals_one(db, order)
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

    if data.desired_date is not None:
        order.desired_date = data.desired_date
        changed = True

    if data.driver_id is not None:
        # Только staff может менять водителя
        if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
            raise ForbiddenError("Только менеджер или администратор может переназначить водителя")
        order.driver_id = data.driver_id
        changed = True

    if was_accepted and changed:
        order.pending_driver_ack = True

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
    return order


async def transition_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: OrderStatusTransitionRequest,
    actor: TokenUser,
) -> Order:
    order = await get_order(db, order_id, actor)

    validate_transition(order.status, data.to_status, actor.role)

    # ACCEPTED→DELIVERED: водитель обязан указать номер ТТН
    if data.to_status == OrderStatus.DELIVERED:
        if actor.role == ROLE_DRIVER:
            if not order.driver_id or order.driver_id != actor.id:
                raise StatusTransitionError("Сначала возьмите заявку через кнопку «Взять»")
        ttn = data.ttn_number or ""
        if not ttn.strip():
            raise StatusTransitionError("Укажите номер ТТН (ttn_number) для отметки о доставке")
        order.ttn_number = ttn.strip()

        # Фиксируем доставленный объём
        order.volume_delivered = float(order.volume_requested)

        # Пересчитываем final_amount
        ctx = await get_client_context(order.client_id)
        recalc = await compute_expected_amount(
            db, order.fuel_type, float(order.volume_delivered), ctx.tariff_id, ctx.client_type
        )
        if recalc is not None:
            order.final_amount = recalc

    if data.to_status == OrderStatus.CANCELLED:
        if data.rejection_reason:
            order.rejection_reason = data.rejection_reason

    prev_status = order.status
    order.status = data.to_status

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
            for gen_fn, label in [
                (document_service.generate_invoice_final, "invoice_final"),
            ]:
                try:
                    async with db.begin_nested():
                        await gen_fn(db, order, actor)
                except Exception as exc:
                    log.warning("Auto-%s generation failed for order %s: %s", label, order.id, exc)

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

    await publish_order_event({
        "event": "order_status",
        "order_id": str(order.id),
        "client_id": str(order.client_id),
        "manager_id": str(order.manager_id) if order.manager_id else None,
        "driver_id": str(order.driver_id) if order.driver_id else None,
        "status": order.status.value,
        "title": f"Статус заявки №{order.order_number} изменён",
        "body": f"Новый статус: {order.status.value}",
    })

    await attach_payment_totals_one(db, order)
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
