import uuid
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field

from app.database import get_db
from app.core.dependencies import CurrentUser
from app.models.order import Order
from app.models.payment import Payment, PaymentStatus, PaymentMethod, PaymentKind
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    client_id: uuid.UUID
    kind: PaymentKind
    status: PaymentStatus
    method: PaymentMethod | None
    amount: float
    invoice_number: str | None
    paid_at: datetime | None
    notes: str | None
    created_by_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RecordPaymentRequest(BaseModel):
    order_id: uuid.UUID
    amount: float = Field(..., gt=0)
    method: PaymentMethod
    notes: str | None = None


@router.get("", response_model=list[PaymentResponse])
async def list_payments(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    order_id: uuid.UUID | None = Query(None),
    client_id: uuid.UUID | None = Query(None),
    status: PaymentStatus | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    return await payment_service.list_payments(
        db, current_user,
        order_id=order_id, client_id=client_id, status=status,
        date_from=date_from, date_to=date_to, offset=offset, limit=limit,
    )


@router.get("/report")
async def payment_report(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
):
    return await payment_service.payment_report(
        db, current_user, date_from=date_from, date_to=date_to
    )


@router.post("/record", response_model=PaymentResponse)
async def record_payment(
    data: RecordPaymentRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Зафиксировать оплату вручную (менеджер / администратор)."""
    return await payment_service.record_payment(
        db, data.order_id, data.amount, data.method.value,
        current_user, notes=data.notes,
    )


class InvoiceRequest(BaseModel):
    basis: str = "requested"  # "requested" — предоплата, "delivered" — по факту
    fuel_coeff: float = Field(1.0, ge=0.1, le=10.0)
    delivery_coeff: float = Field(1.0, ge=0.1, le=10.0)


@router.post("/orders/{order_id}/invoice", response_model=PaymentResponse)
async def create_invoice(
    order_id: uuid.UUID,
    data: InvoiceRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Сформировать счёт для заявки."""
    return await payment_service.create_invoice(
        db, order_id, data.basis, current_user,
        fuel_coeff=data.fuel_coeff, delivery_coeff=data.delivery_coeff,
    )


@router.get("/orders/{order_id}/invoice/{payment_id}/html", response_class=HTMLResponse)
async def get_invoice_html(
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Вернуть HTML счёта для просмотра / печати."""
    from app.core.exceptions import NotFoundError, ForbiddenError as _ForbiddenError
    p_result = await db.execute(
        select(Payment).where(Payment.id == payment_id, Payment.order_id == order_id)
    )
    payment = p_result.scalar_one_or_none()
    if not payment:
        raise NotFoundError("Счёт не найден")

    # Клиент видит только свои счета; менеджер/admin — любые
    if current_user.role == "client" and payment.client_id != current_user.id:
        raise _ForbiddenError()

    o_result = await db.execute(select(Order).where(Order.id == order_id))
    order = o_result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена")

    # В реальной системе — подтягиваем данные клиента из auth_service
    # Пока передаём заглушку; фронтенд может обогатить
    client_info = {"name": str(payment.client_id), "inn": "—", "address": "—"}

    html = payment_service.generate_invoice_html(payment, order, client_info)
    return HTMLResponse(content=html)
