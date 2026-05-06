import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models.order import Order, OrderStatus, PaymentType, OrderPriority
from app.models.order_status_log import OrderStatusLog
from app.core.dependencies import TokenUser
from app.core.status_machine import validate_transition
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.schemas.order import OrderCreateRequest, OrderUpdateRequest, OrderStatusTransitionRequest
from app.services.order_number import generate_order_number
from app.core.events import publish_order_event

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
    # Водитель видит только назначенные на него или в статусе in_progress/assigned
    if actor.role == ROLE_DRIVER:
        visible = {OrderStatus.IN_PROGRESS, OrderStatus.ASSIGNED, OrderStatus.IN_TRANSIT}
        if order.status not in visible and order.driver_id != actor.id:
            raise ForbiddenError()

    return order


async def list_orders(
    db: AsyncSession,
    actor: TokenUser,
    *,
    status: OrderStatus | None = None,
    driver_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list[Order]:
    conditions = [Order.is_archived == False]  # noqa: E712

    if actor.role == ROLE_CLIENT:
        conditions.append(Order.client_id == actor.id)
    elif actor.role == ROLE_DRIVER:
        # Водитель видит: назначенные на него + все свободные in_progress/assigned
        from sqlalchemy import or_
        conditions.append(
            or_(
                Order.driver_id == actor.id,
                and_(
                    Order.status.in_([OrderStatus.IN_PROGRESS, OrderStatus.ASSIGNED]),
                    Order.driver_id == None,  # noqa: E711
                ),
            )
        )
    # Manager/admin видят все

    if status:
        conditions.append(Order.status == status)
    if driver_id and actor.role in (ROLE_MANAGER, ROLE_ADMIN):
        conditions.append(Order.driver_id == driver_id)

    result = await db.execute(
        select(Order).where(and_(*conditions))
        .order_by(Order.created_at.desc())
        .offset(offset).limit(limit)
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

    # Клиент не может оформить заказ в кредит — только менеджер вправе это разрешить
    if not is_staff and data.payment_type == PaymentType.CREDIT:
        raise ValidationError("Клиент не может оформить заказ с типом оплаты «кредит»")

    # Дата доставки не может быть в прошлом
    if data.desired_date:
        if data.desired_date.replace(tzinfo=None) < datetime.now(timezone.utc).replace(tzinfo=None):
            raise ValidationError("Желаемая дата доставки не может быть в прошлом")

    order_number = await generate_order_number(db)

    # Менеджер может сразу поставить «В работе», клиент создаёт только «Новую»
    initial_status = OrderStatus.NEW
    if is_staff and data.start_in_progress:
        initial_status = OrderStatus.IN_PROGRESS

    order = Order(
        order_number=order_number,
        client_id=client_id,
        manager_id=actor.id if is_staff else None,
        fuel_type=data.fuel_type,
        volume_requested=data.volume_requested,
        delivery_address=data.delivery_address,
        desired_date=data.desired_date,
        payment_type=data.payment_type,
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
    if data.driver_id is not None:
        order.driver_id = data.driver_id
    if data.desired_date is not None:
        order.desired_date = data.desired_date

    return order


async def transition_status(
    db: AsyncSession,
    order_id: uuid.UUID,
    data: OrderStatusTransitionRequest,
    actor: TokenUser,
) -> Order:
    order = await get_order(db, order_id, actor)

    validate_transition(order.status, data.to_status, actor.role)

    # Бизнес-проверки при конкретных переходах
    if data.to_status == OrderStatus.ASSIGNED:
        driver_id = data.driver_id or order.driver_id
        if not driver_id:
            from app.core.exceptions import StatusTransitionError
            raise StatusTransitionError("Для назначения укажите driver_id")
        order.driver_id = driver_id
        if not order.manager_id:
            order.manager_id = actor.id

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
        max_allowed = order.volume_requested * 1.05
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
