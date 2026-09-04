"""
Финансовый обзор: сводка по платежам + выгрузка в Excel.
Доступен только менеджерам и администраторам.
"""
import asyncio
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from pydantic import BaseModel

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.exceptions import ForbiddenError
from app.models.order import Order, OrderKind, OrderStatus, PaymentType
from app.models.payment import Payment, PaymentStatus
from app.services.payment_service import get_paid_totals_map
from app.services.buyer_info import attach_buyer_names
from app.services.finance_export import finance_payments_xlsx
from app.services.ttn_number import TtnKind

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

    # Суммы по оплаченным платежам (за период)
    total_paid_amount: float
    total_pending_amount: float

    # Денежные показатели по заявкам в периоде
    total_expected_amount: float      # суммарное ожидаемое поступление (final|expected)
    total_received_amount: float      # уже получено по этим заявкам (PAID платежи)
    total_debt_amount: float          # долг = expected - received по unpaid/partial
    orders_without_pricing: int       # заявки без рассчитанной expected_amount (тариф не настроен)

    # Разбивка по типам оплаты
    by_payment_type: dict[str, int]  # payment_type → кол-во заявок


class PaymentRow(BaseModel):
    payment_id: str
    order_number: str
    client_id: str
    payment_type: str
    order_kind: str      # вид заявки: individual|company|ttn_l
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


# Решение заказчика 24.08.2026: отменённые и архивные заявки в финансах не
# считаем НИГДЕ — ни в сводке, ни в списке платежей, ни в выгрузке. Раньше
# сводка их исключала, а платежи/выгрузка включали — числа не бились.
def _active_order_conds():
    return [
        Order.is_archived == False,  # noqa: E712
        Order.status != OrderStatus.CANCELLED,
    ]


def _kind_conds(kind: OrderKind | None):
    """Фильтр по виду заявки (физ/юр/ТТН-Л) — общий для сводки, списка и выгрузки."""
    return [Order.order_kind == kind] if kind else []


def _ttn_kind_conds(ttn_kind: "TtnKind | None"):
    """Фильтр по типу ТТН (Ю/Ф/Л) — CRM-42, для отчётов с колонкой ТТН."""
    return [Order.ttn_kind == ttn_kind.value] if ttn_kind else []


# Валидацию значения делает FastAPI по enum (невалидное → 422).
KindQuery = Annotated[OrderKind | None, Query(description="Вид заявки: individual|company|ttn_l")]
TtnKindQuery = Annotated[
    TtnKind | None,
    Query(description="Тип ТТН: company (Ю) | individual (Ф) | special (Л)"),
]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/summary", response_model=PaymentSummary)
async def get_summary(
    _: StaffOnly,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to:   datetime | None = Query(None),
    kind: KindQuery = None,
    ttn_kind: TtnKindQuery = None,
):
    """Сводка: кол-во заявок по статусу оплаты + суммы (ожидание / получено / долг)."""
    # Заявки в диапазоне дат (фильтр по created_at заявки)
    order_conds = []
    if date_from:
        order_conds.append(Order.created_at >= date_from)
    if date_to:
        order_conds.append(Order.created_at <= date_to)
    # Отклонённые/архивные заявки не учитываем в финансовых ожиданиях
    order_conds.extend(_active_order_conds())
    order_conds.extend(_kind_conds(kind))
    order_conds.extend(_ttn_kind_conds(ttn_kind))

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

    # Суммы платежей за период (фильтр по дате создания платежа)
    pay_conds = _date_conditions(date_from, date_to) + _active_order_conds() + _kind_conds(kind) + _ttn_kind_conds(ttn_kind)
    paid_q = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.status == PaymentStatus.PAID, *pay_conds)
    )
    pending_q = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(Order, Order.id == Payment.order_id)
        .where(Payment.status == PaymentStatus.PENDING, *pay_conds)
    )
    paid_sum = float((await db.execute(paid_q)).scalar() or 0)
    pending_sum = float((await db.execute(pending_q)).scalar() or 0)

    # Денежные показатели по заявкам периода
    paid_per_order = await get_paid_totals_map(db, [o.id for o in orders])
    total_expected = 0.0
    total_received = 0.0
    total_debt = 0.0
    no_pricing = 0
    for o in orders:
        target = o.final_amount if o.final_amount is not None else o.expected_amount
        order_paid = float(paid_per_order.get(o.id, 0))
        total_received += order_paid
        if target is None:
            no_pricing += 1
            continue
        target_f = float(target)
        total_expected += target_f
        if o.payment_status in ("unpaid", "partially_paid"):
            total_debt += max(target_f - order_paid, 0.0)

    return PaymentSummary(
        total_orders=len(orders),
        unpaid_count=unpaid,
        partially_paid_count=partial,
        paid_count=paid,
        overpaid_count=overpaid,
        total_paid_amount=paid_sum,
        total_pending_amount=pending_sum,
        total_expected_amount=round(total_expected, 2),
        total_received_amount=round(total_received, 2),
        total_debt_amount=round(total_debt, 2),
        orders_without_pricing=no_pricing,
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
    kind: KindQuery = None,
    ttn_kind: TtnKindQuery = None,
    offset: int = Query(0, ge=0),
    limit:  int = Query(100, ge=1, le=500),
):
    """Список платежей с фильтрацией — для таблицы на вкладке Финансы."""
    conds = _date_conditions(date_from, date_to) + _active_order_conds() + _kind_conds(kind) + _ttn_kind_conds(ttn_kind)
    if status:
        conds.append(Payment.status == status)

    q = (
        select(Payment, Order.order_number, Order.payment_type, Order.order_kind)
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
            order_kind=order_kind.value if hasattr(order_kind, "value") else str(order_kind),
            kind=p.kind.value,
            status=p.status.value,
            method=p.method.value if p.method else None,
            amount=float(p.amount),
            paid_at=p.paid_at,
            notes=p.notes,
            created_at=p.created_at,
        )
        for p, order_number, payment_type, order_kind in rows
    ]


XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


# Старый путь /export.csv сохранён как алиас: закладки и мобильный клиент
# продолжают работать, но отдаётся тот же XLSX (CSV с запятой русский Excel
# открывал одной колонкой — «поля поехали»).
@router.get("/export.xlsx")
@router.get("/export.csv", include_in_schema=False)
async def export_xlsx(
    _: StaffOnly,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(None),
    date_to:   datetime | None = Query(None),
    kind: KindQuery = None,
    ttn_kind: TtnKindQuery = None,
):
    """Выгрузка платежей за период в Excel (.xlsx)."""
    conds = _date_conditions(date_from, date_to) + _active_order_conds() + _kind_conds(kind) + _ttn_kind_conds(ttn_kind)
    q = (
        select(Payment, Order)
        .join(Order, Order.id == Payment.order_id)
        .where(*conds)
        .order_by(Payment.created_at.desc())
    )
    rows = list((await db.execute(q)).all())

    # Имена клиентов/организаций — ОДИН батч-запрос в auth на весь отчёт
    # (не N+1). Уникальные заявки, чтобы не гонять один и тот же client дважды.
    unique_orders = list({order.id: order for _, order in rows}.values())
    await attach_buyer_names(unique_orders)

    payments = [
        {
            "payment_id":   str(p.id),
            "order_number": order.order_number,
            "order_kind": (
                order.order_kind.value
                if hasattr(order.order_kind, "value")
                else str(order.order_kind or "")
            ),
            "ttn_number":   order.ttn_number,
            "client_name":  getattr(order, "buyer_name", None),
            "payment_type": (
                order.payment_type.value
                if hasattr(order.payment_type, "value")
                else str(order.payment_type)
            ),
            "kind":       p.kind.value,
            "status":     p.status.value,
            "method":     p.method.value if p.method else None,
            "amount":     float(p.amount),
            "paid_at":    p.paid_at,
            "created_at": p.created_at,
            "notes":      p.notes,
        }
        for p, order in rows
    ]

    report = {
        "period_from": date_from,
        "period_to":   date_to,
        "payments":    payments,
    }
    # openpyxl синхронен — уводим в тред, чтобы не блокировать event loop.
    xlsx_bytes = await asyncio.to_thread(finance_payments_xlsx, report)

    filename = f"finance_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return Response(
        content=xlsx_bytes,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
