import logging
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

import httpx
from jose import jwt as jose_jwt

from app.config import get_settings as _get_settings
from app.models.order import Order, OrderStatus, PaymentType, OrderPriority
from app.models.order_status_log import OrderStatusLog
from app.core.dependencies import TokenUser
from app.core.status_machine import validate_transition
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError, StatusTransitionError
from app.schemas.order import OrderCreateRequest, OrderUpdateRequest, OrderStatusTransitionRequest
from app.services.order_number import generate_order_number
from app.services.payment_service import recompute_and_save
from app.services import document_service
from app.services.client_context import get_client_context
from app.services.payment_type_rules import validate_payment_type
from app.services.pricing_service import compute_expected_amount
from app.core.events import publish_order_event

log = logging.getLogger(__name__)

DELIVERY_SERVICE_URL = "http://delivery_service:8003"


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


async def _auto_start_trip(order: Order, actor: TokenUser) -> None:
    """Создать и запустить рейс в delivery_service при переводе заявки в in_transit.

    Если топлива недостаточно — delivery_service возвращает 422, и мы
    пробрасываем ошибку: order_service не меняет статус заявки.
    Если delivery_service недоступен — raise StatusTransitionError (fail-closed).
    """
    try:
        token = _make_service_token(actor)
        payload = {
            "order_id": str(order.id),
            "driver_id": str(order.driver_id),
            "inv_fuel_type": order.fuel_type.value if order.fuel_type else None,
            "inv_order_number": order.order_number,
            "inv_client_id": str(order.client_id),
            "volume_planned": float(order.volume_requested),
            "delivery_address": order.delivery_address or "",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{DELIVERY_SERVICE_URL}/api/v1/trips/auto-start",
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            )
        if r.status_code in (200, 201):
            return  # success
        detail = r.json().get("detail", f"Ошибка сервиса доставки: {r.status_code}")
        raise StatusTransitionError(detail)
    except StatusTransitionError:
        raise
    except Exception as exc:
        log.error("_auto_start_trip failed for order %s: %s", order.id, exc)
        raise StatusTransitionError(
            "Не удалось запустить рейс: сервис доставки недоступен. Попробуйте позже."
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
    # Водитель видит только свои заявки (driver_id == actor.id)
    if actor.role == ROLE_DRIVER and order.driver_id != actor.id:
        raise ForbiddenError()

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
        # Водитель видит: свои заявки + свободные in_progress (биржа)
        from sqlalchemy import or_
        conditions.append(
            or_(
                Order.driver_id == actor.id,
                and_(
                    Order.status == OrderStatus.IN_PROGRESS,
                    Order.driver_id == None,  # noqa: E711
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
    return list(result.scalars().all())


async def create_order(
    db: AsyncSession,
    data: OrderCreateRequest,
    actor: TokenUser,
) -> Order:
    is_staff = actor.role in (ROLE_MANAGER, ROLE_ADMIN)

    if not is_staff and actor.role != ROLE_CLIENT:
        raise ForbiddenError("Создание заявок доступно клиентам, менеджерам и администраторам")

    # Менеджер/Админ может создать заявку от имени клиента
    if is_staff:
        client_id = data.client_id or actor.id
    else:
        if data.client_id:
            raise ForbiddenError("Клиент не может указывать client_id")
        client_id = actor.id

    # Fetch client context (client_type, credit_allowed, tariff_id) from auth_service.
    # Fails with 503 if auth_service is unreachable — we never silently skip this check.
    ctx = await get_client_context(client_id)

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

    order_number = await generate_order_number(db)

    # Менеджер может сразу поставить «В работе», клиент создаёт только «Новую»
    initial_status = OrderStatus.NEW
    if is_staff and data.start_in_progress:
        initial_status = OrderStatus.IN_PROGRESS

    # Compute expected_amount from tariff (None if tariff not configured — non-fatal)
    expected_amount = await compute_expected_amount(
        db, data.fuel_type, data.volume_requested, ctx.tariff_id
    )

    order = Order(
        order_number=order_number,
        client_id=client_id,
        manager_id=actor.id if is_staff else None,
        fuel_type=data.fuel_type,
        volume_requested=data.volume_requested,
        delivery_address=data.delivery_address,
        desired_date=data.desired_date,
        payment_type=data.payment_type,
        expected_amount=expected_amount,
        priority=data.priority if is_staff else OrderPriority.NORMAL,
        client_comment=data.client_comment,
        manager_comment=data.manager_comment if is_staff else None,
        status=initial_status,
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

    # Если менеджер сразу взял в работу — добавляем второй лог-переход
    if initial_status == OrderStatus.IN_PROGRESS:
        db.add(OrderStatusLog(
            order_id=order.id,
            from_status=OrderStatus.NEW,
            to_status=OrderStatus.IN_PROGRESS,
            changed_by_id=actor.id,
            changed_by_role=actor.role,
            comment="Автоматически принята при создании",
        ))

    await db.flush()

    # Auto-document: prepaid → invoice_preliminary at creation time
    if order.payment_type == PaymentType.PREPAID:
        try:
            await document_service.generate_invoice_preliminary(db, order, actor)
        except Exception as exc:
            log.warning("Auto-invoice_preliminary failed for order %s: %s", order.id, exc)

    # Re-fetch with eager-loaded status_logs to avoid lazy-load error during serialization
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

    if data.priority is not None:
        order.priority = data.priority
    if data.manager_comment is not None:
        order.manager_comment = data.manager_comment
    if data.desired_date is not None:
        order.desired_date = data.desired_date
    if data.expected_amount is not None:
        order.expected_amount = data.expected_amount
    if data.trade_credit_contract_signed is not None:
        order.trade_credit_contract_signed = data.trade_credit_contract_signed

    # final_amount меняет цель — пересчитываем payment_status
    if data.final_amount is not None:
        order.final_amount = data.final_amount
        await recompute_and_save(db, order)

    # driver_id больше не назначается менеджером — водители берут заявки через /claim

    return order


async def claim_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser,
) -> Order:
    """Водитель берёт свободную заявку из биржи (IN_PROGRESS, driver_id IS NULL).
    Атомарная операция: UPDATE ... WHERE driver_id IS NULL защищает от гонки.
    """
    if actor.role != ROLE_DRIVER:
        raise ForbiddenError("Взять заявку может только водитель")

    result = await db.execute(
        _with_logs(
            select(Order).where(
                Order.id == order_id,
                Order.is_archived == False,  # noqa: E712
                Order.status == OrderStatus.IN_PROGRESS,
                Order.driver_id == None,  # noqa: E711
            )
        )
    )
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена или уже занята другим водителем")

    order.driver_id = actor.id
    await db.flush()

    db.add(OrderStatusLog(
        order_id=order.id,
        from_status=order.status,
        to_status=order.status,
        changed_by_id=actor.id,
        changed_by_role=actor.role,
        comment="Заявка взята водителем",
    ))

    result = await db.execute(_with_logs(select(Order).where(Order.id == order.id)))
    return result.scalar_one()


async def transition_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: OrderStatusTransitionRequest,
    actor: TokenUser,
) -> Order:
    order = await get_order(db, order_id, actor)

    validate_transition(order.status, data.to_status, actor.role)

    # Бизнес-проверки при конкретных переходах

    # Шлагбаум закрытия: заявка не закрывается без оплаты.
    # Исключение: кредитные типы (trade_credit / debt) с подписанным договором —
    # закрываются без оплаты (долг фиксируется в отчётности).
    if data.to_status == OrderStatus.CLOSED:
        is_credit_payment = order.payment_type in (
            PaymentType.TRADE_CREDIT, PaymentType.DEBT
        )
        credit_bypass = is_credit_payment and order.trade_credit_contract_signed
        if order.payment_status != "paid" and not credit_bypass:
            raise StatusTransitionError(
                f"Нельзя закрыть заявку: статус оплаты «{order.payment_status}». "
                "Зафиксируйте оплату или, для товарного кредита / долга, "
                "отметьте подписание договора."
            )

    # При переводе в in_transit — автоматически создаём рейс и списываем топливо.
    # Если delivery_service вернёт ошибку (нет топлива, недоступен) — прерываем переход.
    if data.to_status == OrderStatus.IN_TRANSIT:
        await _auto_start_trip(order, actor)

    # При переводе in_progress → in_transit водитель должен быть уже в driver_id (через /claim)
    if data.to_status == OrderStatus.IN_TRANSIT and actor.role == ROLE_DRIVER:
        if not order.driver_id or order.driver_id != actor.id:
            from app.core.exceptions import StatusTransitionError
            raise StatusTransitionError("Сначала возьмите заявку через кнопку «Взять»")

    if data.to_status == OrderStatus.REJECTED:
        if not data.rejection_reason:
            from app.core.exceptions import StatusTransitionError
            raise StatusTransitionError("Укажите причину отклонения")
        order.rejection_reason = data.rejection_reason

    if data.to_status in (OrderStatus.DELIVERED, OrderStatus.PARTIALLY_DELIVERED):
        from app.core.exceptions import StatusTransitionError
        if data.volume_delivered is None:
            raise StatusTransitionError("Укажите фактический объём доставки (volume_delivered)")
        if data.volume_delivered <= 0:
            raise StatusTransitionError("volume_delivered должен быть > 0")
        # Разрешаем до 5 % погрешности сверх заказанного объёма
        max_allowed = float(order.volume_requested) * 1.05
        if data.volume_delivered > max_allowed:
            raise StatusTransitionError(
                f"volume_delivered ({data.volume_delivered} л) превышает заказанный объём "
                f"({order.volume_requested} л) более чем на 5 %"
            )
        order.volume_delivered = data.volume_delivered

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

    # ── Авто-генерация документов ─────────────────────────────────────────────
    # Ошибки PDF-рендера не прерывают переход — документ остаётся в статусе DRAFT.
    #
    # Матрица триггеров (SPEC 1.5.9):
    #   IN_TRANSIT   + trade_credit/debt  → TTN предварительная
    #   DELIVERED/*  + все типы           → invoice_final + UPD + TTN финальная
    #   (prepaid получает invoice_preliminary при создании, не здесь)

    _credit_types = (PaymentType.TRADE_CREDIT, PaymentType.DEBT)

    if data.to_status == OrderStatus.IN_TRANSIT:
        if order.payment_type in _credit_types:
            try:
                await document_service.generate_ttn(db, order, actor)
            except Exception as exc:
                log.warning("Auto-TTN (preliminary) failed for order %s: %s", order.id, exc)

    if data.to_status in (OrderStatus.DELIVERED, OrderStatus.PARTIALLY_DELIVERED):
        for gen_fn, label in [
            (document_service.generate_invoice_final, "invoice_final"),
            (document_service.generate_upd, "UPD"),
            (document_service.generate_ttn, "TTN"),
        ]:
            try:
                await gen_fn(db, order, actor)
            except Exception as exc:
                log.warning("Auto-%s generation failed for order %s: %s", label, order.id, exc)

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
