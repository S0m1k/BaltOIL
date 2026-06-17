"""Запрос доставленных заявок водителя за период — для отчёта delivery_service.

Дата доставки определяется по записи в истории статусов (OrderStatusLog),
где to_status == DELIVERED. Это фактический момент подтверждения доставки,
а не плановая дата заявки.
"""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.order_status_log import OrderStatusLog
from app.schemas.driver_report import DriverOrderInfo


async def list_driver_delivered_orders(
    db: AsyncSession,
    *,
    driver_id: uuid.UUID,
    date_from: datetime,
    date_to: datetime,
) -> list[DriverOrderInfo]:
    log = OrderStatusLog
    stmt = (
        select(Order, log.created_at.label("delivered_at"))
        .join(log, log.order_id == Order.id)
        .where(
            Order.driver_id == driver_id,
            Order.status == OrderStatus.DELIVERED,
            log.to_status == OrderStatus.DELIVERED,
            log.created_at >= date_from,
            log.created_at <= date_to,
        )
        .order_by(log.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    return [
        DriverOrderInfo(
            order_id=order.id,
            order_number=order.order_number,
            fuel_type=order.fuel_type,
            volume_delivered=(
                float(order.volume_delivered) if order.volume_delivered is not None else None
            ),
            delivery_address=order.delivery_address,
            client_id=order.client_id,
            delivered_at=delivered_at,
        )
        for order, delivered_at in rows
    ]
