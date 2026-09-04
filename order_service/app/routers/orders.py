import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import OrderStatus, OrderKind
from app.core.dependencies import CurrentUser
from app.core.status_machine import ROLE_CLIENT
from app.schemas.order import (
    OrderCreateRequest, OrderUpdateRequest, OrderStatusTransitionRequest,
    RescheduleRequest, OrderResponse, OrderListResponse,
    PricePreviewRequest, PricePreviewResponse, ShipmentOverrideRequest,
)
from app.schemas.order_audit import OrderAuditLogResponse
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


def _hide_internal(order, actor, model):
    """CRM-41: комментарий менеджера — внутренний (сотрудники и водитель).

    Единственное место, где ответ заявки «обрезается» под роль: клиенту поле
    отдаётся как None. Исходный объект не трогаем — иначе SQLAlchemy запишет
    очистку комментария в БД при ближайшем commit.

    `model_copy` обязателен: `model_validate` на уже готовом экземпляре модели
    возвращает ЕГО ЖЕ (pydantic v2, revalidate_instances="never"), и правка
    поля ушла бы в исходный объект.
    """
    if actor.role != ROLE_CLIENT:
        return order
    if isinstance(order, list):
        return [_hide_internal(o, actor, model) for o in order]
    return model.model_validate(order).model_copy(update={"manager_comment": None})


@router.get("", response_model=list[OrderListResponse])
async def list_orders(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: OrderStatus | None = Query(None),
    driver_id: uuid.UUID | None = Query(None),
    client_id: uuid.UUID | None = Query(None),
    kind: OrderKind | None = Query(None, description="Вид заявки: individual | company | ttn_l"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    orders = await order_service.list_orders(
        db, current_user, status=status, driver_id=driver_id, client_id=client_id,
        kind=kind, offset=offset, limit=limit
    )
    return _hide_internal(orders, current_user, OrderListResponse)


@router.get("/counts", response_model=dict[str, int])
async def count_orders(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    kind: OrderKind | None = Query(None, description="Вид заявки: individual | company | ttn_l"),
):
    """Счётчики заявок по статусам (в пределах видимости роли) — для бейджей вкладок."""
    return await order_service.count_orders_by_status(db, current_user, kind=kind)


@router.get("/last-delivery-by-client", response_model=dict[str, str])
async def last_delivery_by_client(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Дата последней доставки по каждому клиенту: {client_id: ISO-дата}.

    Для базы разовых клиентов (правки 2026-07-11). Только менеджер/админ.
    """
    return await order_service.last_delivery_by_client(db, current_user)


@router.post("/preview-price", response_model=PricePreviewResponse)
async def preview_price(
    data: PricePreviewRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Read-only price breakdown for the create form. No DB writes."""
    return await order_service.preview_price(db, data, current_user)


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    data: OrderCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.create_order(db, data, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.get_order(db, order_id, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.get("/{order_id}/audit", response_model=list[OrderAuditLogResponse])
async def get_order_audit(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """CRM-44: журнал действий по заявке — кто создал, менял поля, отмечал оплату.

    Только администратор: журнал поимённый и содержит внутренние правки.
    """
    return await order_service.get_order_audit(db, order_id, current_user)


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: uuid.UUID,
    data: OrderUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    order = await order_service.update_order(db, order_id, data, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.post("/{order_id}/transition", response_model=OrderResponse)
async def transition_status(
    order_id: uuid.UUID,
    data: OrderStatusTransitionRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Смена статуса заявки. Допустимые переходы зависят от роли пользователя."""
    order = await order_service.transition_status(
        db, order_id, data, current_user,
        idempotency_key=str(data.idempotency_key) if data.idempotency_key else None,
    )
    return _hide_internal(order, current_user, OrderResponse)


@router.post("/{order_id}/claim", response_model=OrderResponse)
async def claim_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель берёт свободную заявку (NEW, без водителя) → переходит в ACCEPTED."""
    order = await order_service.claim_order(db, order_id, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.post("/{order_id}/ack-changes", response_model=OrderResponse)
async def ack_changes(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель подтверждает, что увидел изменения в заявке. Снимает флаг pending_driver_ack."""
    order = await order_service.ack_changes(db, order_id, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.post("/{order_id}/shipment", response_model=OrderResponse)
async def set_shipment_override(
    order_id: uuid.UUID,
    data: ShipmentOverrideRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Отгрузка (правки 2026-07-25, менеджер/админ): 'allow' — разрешить
    (разово, даже без оплаты), 'hold' — «ждём оплату», 'auto' — вернуть
    автоматический расчёт от оплаты/типа клиента."""
    order = await order_service.set_shipment_override(db, order_id, data.mode, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.post("/{order_id}/ack-comment", response_model=OrderResponse)
async def ack_comment(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель подтверждает, что увидел комментарий к заявке (правки 2026-07-25)."""
    order = await order_service.ack_comment(db, order_id, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.post("/{order_id}/reschedule", response_model=OrderResponse)
async def reschedule_order(
    order_id: uuid.UUID,
    data: RescheduleRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Перенос заявки: смена desired_date и/или driver_id."""
    order = await order_service.reschedule_order(db, order_id, data, current_user)
    return _hide_internal(order, current_user, OrderResponse)


@router.delete("/{order_id}", status_code=204)
async def archive_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await order_service.archive_order(db, order_id, current_user)


@router.delete("/{order_id}/hard")
async def hard_delete_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Полное удаление заявки без возможности восстановления (только админ).

    В отличие от DELETE /orders/{id} (архивирование) удаляет документы, платежи,
    историю статусов, а по событию order_deleted — рейсы, складские проводки,
    чат заявки и уведомления в смежных сервисах.
    """
    return await order_service.hard_delete_order(db, order_id, current_user)
