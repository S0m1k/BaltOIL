"""Заявки на перевозку: /transport/orders.

Сами заявки живут в общем реестре (GET /orders — перевозка приходит там же,
в общем порядке, с order_kind='transport'). Эти эндпоинты добавляют то, чего
в общем реестре нет: создание по форме перевозки, правку её полей и окно
«доставлено» водителя.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.database import get_db
from app.schemas.order import OrderResponse
from app.schemas.transport import (
    TransportDeliverRequest, TransportDetailResponse,
    TransportOrderCreateRequest, TransportOrderUpdateRequest,
)
from app.services import transport_service

router = APIRouter(prefix="/transport/orders", tags=["transport"])


@router.post("", response_model=OrderResponse, status_code=201)
async def create_transport_order(
    data: TransportOrderCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Создать заявку на перевозку (только менеджер и администратор)."""
    return await transport_service.create_transport_order(db, data, current_user)


@router.get("/{order_id}", response_model=TransportDetailResponse)
async def get_transport_detail(
    order_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Детали перевозки. Водителю отдаётся только блок 1 (без денег)."""
    order = await transport_service.get_transport_order(db, order_id, current_user)
    return await transport_service.detail_response(db, order, current_user)


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_transport_order(
    order_id: uuid.UUID,
    data: TransportOrderUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Правка любого поля отправленной заявки (менеджер и администратор)."""
    return await transport_service.update_transport_order(db, order_id, data, current_user)


@router.post("/{order_id}/deliver", response_model=OrderResponse)
async def deliver_transport_order(
    order_id: uuid.UUID,
    data: TransportDeliverRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Водитель отмечает перевозку доставленной, подтвердив маршрут и дату."""
    return await transport_service.deliver_transport_order(db, order_id, data, current_user)
