"""
Финансовый обзор: сводка по платежам + CSV-экспорт.
Доступен только менеджерам и администраторам.
"""
import csv
import io
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from pydantic import BaseModel

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.exceptions import ForbiddenError
from app.models.order import Order, PaymentType
from app.models.payment import Payment, PaymentStatus

router = APIRouter(prefix="/finance", tags=["finance"])

StaffOnly = Annotated[object, Depends(require_roles("manager", "admin"))]


# ── Schemas ───────────────────────────────────────────────────────────────────

class PaymentSummary(BaseModel):
    # Итоги по статусам оплаты заявок
    total_orders: int
    unpaid_count: int
    partially_paid_count: int
    paid_count: int
    overpaid_count: int

    # Суммы по оплаченным платежам
    total_paid_amount: float
    total_pending_amount: float

    # Разбивка по типам оплаты
    by_payment_type: dict[str, int]  # payment_type → кол-во заявок


class PaymentRow(BaseModel):
    payment_id: str
    order_number: str
    client_id: str
    payment_type: str
    kind: str
    status: str
    method: str | None
    amount: float
    paid_at: datetime | None
    notes: str | None
    created_at: datetime


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date_conditions(date_from: datetime | None, date_to: datetime | None):
    conds = []
    if date_from:
        conds.append(Payment.created_at >= date_from)
    if date_to:
        conds.append(Payment.created_at <= date_to)
    return conds


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=PaymentSummary)
async def get_summary(
    _: StaffOnly,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to:   datetime | None = Query(None),
):
    """Сводка: кол-во заявок по статусу оплаты + суммы."""
    # Заявки в диапазоне дат (фильтр по created_at заявки)
    order_conds = []
    if date_from:
        order_conds.append(Order.created_at >= date_from)
    if date_to:
        order_conds.append(Order.created_at <= date_to)
    order_conds.append(Order.is_archived == False)  # noqa: E712

    orders_q = select(Order)
    if order_conds:
        orders_q = orders_q.where(and_(*order_conds))
    orders_result = await db.execute(orders_q)
    orders = list(orders_result.scalars().all())

    # Статусы оплаты
    unpaid = sum(1 for o in orders if o.payment_status == "unpaid")
    partial = sum(1 for o in orders if o.payment_status == "partially_paid")
    paid = sum(1 for o in orders if o.payment_status == "paid")
    overpaid = sum(1 for o in orders if o.payment_status == "overpaid")

    # Разбивка по типам оплаты
    by_type: dict[str, int] = {}
    for o in orders:
        key = o.payment_type.value if hasattr(o.payment_type, "value") else str(o.payment_type)
        by_type[key] = by_type.get(key, 0) + 1

    # Суммы платежей за период
    pay_conds = _date_conditions(date_from, date_to)
    paid_q = select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status == PaymentStatus.PAID,
        *pay_conds,
    )
    pending_q = select(func.coalesce(func.sum(Payment.amount), 0)).where(
        Payment.status == PaymentStatus.PENDING,
        *pay_conds,
    )
    paid_sum = float((await db.execute(paid_q)).scalar() or 0)
    pending_sum = float((await db.execute(pending_q)).scalar() or 0)

    return PaymentSummary(
        total_orders=len(orders),
        unpaid_count=unpaid,
        partially_paid_count=partial,
        paid_count=paid,
        overpaid_count=overpaid,
        total_paid_amount=paid_sum,
        total_pending_amount=pending_sum,
        by_payment_type=by_type,
    )


@router.get("/payments", response_model=list[PaymentRow])
async def list_payments(
    _: StaffOnly,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to:   datetime | None = Query(None),
    status: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit:  int = Query(100, ge=1, le=500),
):
    """Список платежей с фильтрацией — для таблицы на вкладке Финансы."""
    conds = _date_conditions(date_from, date_to)
    if status:
        conds.append(Payment.status == status)

    q = (
        select(Payment, Order.order_number, Order.payment_type)
        .join(Order, Order.id == Payment.order_id)
        .where(*conds)
        .order_by(Payment.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await db.execute(q)).all())

    return [
        PaymentRow(
            payment_id=str(p.id),
            order_number=order_number,
            client_id=str(p.client_id),
            payment_type=payment_type.value if hasattr(payment_type, "value") else str(payment_type),
            kind=p.kind.value,
            status=p.status.value,
            method=p.method.value if p.method else None,
            amount=float(p.amount),
            paid_at=p.paid_at,
            notes=p.notes,
            created_at=p.created_at,
        )
        for p, order_number, payment_type in rows
    ]


@router.get("/export.csv")
async def export_csv(
    _: StaffOnly,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to:   datetime | None = Query(None),
):
    """Выгрузка платежей в CSV."""
    conds = _date_conditions(date_from, date_to)
    q = (
        select(Payment, Order.order_number, Order.payment_type)
        .join(Order, Order.id == Payment.order_id)
        .where(*conds)
        .order_by(Payment.created_at.desc())
    )
    rows = list((await db.execute(q)).all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID платежа", "Заявка", "Клиент", "Тип оплаты", "Вид", "Статус",
        "Метод", "Сумма", "Дата оплаты", "Дата создания", "Примечание",
    ])
    for p, order_number, payment_type in rows:
        writer.writerow([
            str(p.id),
            order_number,
            str(p.client_id),
            payment_type.value if hasattr(payment_type, "value") else str(payment_type),
            p.kind.value,
            p.status.value,
            p.method.value if p.method else "",
            float(p.amount),
            p.paid_at.strftime("%d.%m.%Y %H:%M") if p.paid_at else "",
            p.created_at.strftime("%d.%m.%Y %H:%M"),
            p.notes or "",
        ])

    output.seek(0)
    filename = f"payments_{datetime.now().strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),  # utf-8-sig for Excel compatibility
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
