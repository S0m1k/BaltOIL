import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.order import OrderStatus
from app.core.dependencies import CurrentUser
from app.schemas.order import (
    OrderCreateRequest, OrderUpdateRequest, OrderStatusTransitionRequest,
    OrderResponse, OrderListResponse,
)
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", response_model=list[OrderListResponse])
async def list_orders(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    status: OrderStatus | None = Query(None),
    driver_id: uuid.UUID | None = Query(None),
    client_id: uuid.UUID | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    return await order_service.list_orders(
        db, current_user, status=status, driver_id=driver_id, client_id=client_id,
        offset=offset, limit=limit
    )


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    data: OrderCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await order_service.create_order(db, data, current_user)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await order_service.get_order(db, order_id, current_user)


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: uuid.UUID,
    data: OrderUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await order_service.update_order(db, order_id, data, current_user)


@router.post("/{order_id}/transition", response_model=OrderResponse)
async def transition_status(
    order_id: uuid.UUID,
    data: OrderStatusTransitionRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Смена статуса заявки. Допустимые переходы зависят от роли пользователя."""
    return await order_service.transition_status(db, order_id, data, current_user)


@router.post("/{order_id}/claim", response_model=OrderResponse)
async def claim_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель берёт свободную заявку (IN_PROGRESS, без водителя)."""
    return await order_service.claim_order(db, order_id, current_user)


@router.delete("/{order_id}", status_code=204)
async def archive_order(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await order_service.archive_order(db, order_id, current_user)
