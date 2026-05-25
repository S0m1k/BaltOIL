"""
Client-level aggregation endpoints for the client card modal (Deploy 3).

All endpoints require manager or admin role — clients get 403.
"""
import uuid
import logging
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.exceptions import ForbiddenError
from app.models.document import Document, DocumentType, DocumentStatus
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus

log = logging.getLogger(__name__)

router = APIRouter(prefix="/clients", tags=["clients"])

ManagerOrAdmin = Annotated[object, Depends(require_roles("manager", "admin"))]


# ── Schemas ───────────────────────────────────────────────────────────────────

class ClientDocumentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    doc_type: DocumentType
    doc_number: str
    status: DocumentStatus
    issued_at: datetime | None
    total_amount: float | None
    volume: float | None
    file_path: str | None
    created_by_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class ClientPaymentsResponse(BaseModel):
    payments: list[dict]
    total_paid: float
    total_due: float
    balance: float


class ClientSummaryResponse(BaseModel):
    order_counts: dict[str, int]
    total_volume: float
    total_amount: float
    first_order_at: datetime | None
    last_order_at: datetime | None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/{client_id}/documents", response_model=list[ClientDocumentResponse])
async def list_client_documents(
    client_id: uuid.UUID,
    _: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
    doc_type: DocumentType | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """List all documents across all orders of a given client. Manager/admin only."""
    # Join Document → Order to filter by client_id
    conditions = [Order.client_id == client_id, Order.is_archived == False]  # noqa: E712
    if doc_type is not None:
        conditions.append(Document.doc_type == doc_type)

    q = (
        select(Document)
        .join(Order, Document.order_id == Order.id)
        .where(and_(*conditions))
        .order_by(Document.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


@router.get("/{client_id}/payments", response_model=ClientPaymentsResponse)
async def get_client_payments(
    client_id: uuid.UUID,
    _: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """All payments for a client + computed balance (total_paid - total_due)."""
    # Fetch all payments for this client
    payments_result = await db.execute(
        select(Payment)
        .where(Payment.client_id == client_id)
        .order_by(Payment.created_at.desc())
    )
    payments = list(payments_result.scalars().all())

    # total_paid = sum of PAID payments
    total_paid = sum(float(p.amount) for p in payments if p.status == PaymentStatus.PAID)

    # total_due = sum of PENDING payments (invoices not yet paid)
    total_due = sum(float(p.amount) for p in payments if p.status == PaymentStatus.PENDING)

    balance = total_paid - total_due

    payments_dicts = [
        {
            "id": str(p.id),
            "order_id": str(p.order_id),
            "kind": p.kind.value if hasattr(p.kind, "value") else p.kind,
            "status": p.status.value if hasattr(p.status, "value") else p.status,
            "method": p.method.value if (p.method and hasattr(p.method, "value")) else p.method,
            "amount": float(p.amount),
            "invoice_number": p.invoice_number,
            "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "notes": p.notes,
            "created_at": p.created_at.isoformat(),
        }
        for p in payments
    ]

    return ClientPaymentsResponse(
        payments=payments_dicts,
        total_paid=total_paid,
        total_due=total_due,
        balance=balance,
    )


@router.get("/{client_id}/summary", response_model=ClientSummaryResponse)
async def get_client_summary(
    client_id: uuid.UUID,
    _: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Aggregated summary: order counts by status, total volume/amount, first/last order dates."""
    orders_result = await db.execute(
        select(Order).where(Order.client_id == client_id, Order.is_archived == False)  # noqa: E712
    )
    orders = list(orders_result.scalars().all())

    order_counts: dict[str, int] = {}
    for s in OrderStatus:
        order_counts[s.value] = 0
    for o in orders:
        key = o.status.value if hasattr(o.status, "value") else str(o.status)
        order_counts[key] = order_counts.get(key, 0) + 1

    total_volume = sum(
        float(o.volume_delivered or o.volume_requested)
        for o in orders
    )
    total_amount = sum(
        float(o.final_amount or o.expected_amount or 0)
        for o in orders
    )

    dates = [o.created_at for o in orders if o.created_at]
    first_order_at = min(dates) if dates else None
    last_order_at = max(dates) if dates else None

    return ClientSummaryResponse(
        order_counts=order_counts,
        total_volume=total_volume,
        total_amount=total_amount,
        first_order_at=first_order_at,
        last_order_at=last_order_at,
    )
