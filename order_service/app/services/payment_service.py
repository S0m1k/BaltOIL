"""
Сервис управления платежами и формирования счетов.
Тестовые реквизиты СЗТК используются до получения боевых.
"""
import html as _html
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

log = logging.getLogger(__name__)

from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentStatus, PaymentKind, PaymentMethod
from app.models.legal_entity import LegalEntity
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"


async def get_seller_snapshot(db: AsyncSession) -> dict:
    """Загрузить реквизиты продавца из БД для подстановки в документы и счета."""
    from sqlalchemy import select as _select
    result = await db.execute(
        _select(LegalEntity)
        .where(LegalEntity.effective_to.is_(None), LegalEntity.is_active.is_(True))
        .order_by(LegalEntity.effective_from.desc())
        .limit(1)
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        raise ValidationError(
            "Реквизиты продавца не заполнены. "
            "Администратор должен добавить юридическое лицо через /api/v1/admin/legal-entity"
        )
    return {
        "name":    entity.name,
        "inn":     entity.inn or "—",
        "kpp":     entity.kpp or "—",
        "ogrn":    entity.ogrn or "—",
        "address": entity.legal_address or entity.actual_address or "—",
        "phone":   entity.phone or "—",
        "email":   entity.email or "—",
        "bank":    entity.bank_name or "—",
        "rs":      entity.checking_account or "—",
        "ks":      entity.correspondent_account or "—",
        "bik":     entity.bik or "—",
        "director_name":  entity.director_name or "—",
        "director_title": entity.director_title or "Директор",
    }

# Базовые цены топлива (₽/л) — тестовые, из прайса сайта
BASE_FUEL_PRICES = {
    "diesel_summer": 49.0,
    "diesel_winter": 57.0,
    "petrol_92":     59.0,
    "petrol_95":     61.0,
    "fuel_oil":      24.0,   # мазут — за литр (условно)
}
BASE_DELIVERY_PRICE_PER_LITER = 3.0  # ₽/л (тестовое)


# ── Payment status computation ────────────────────────────────────────────────

def compute_payment_status(
    paid_total: Decimal,
    expected_amount: Decimal | None,
    final_amount: Decimal | None,
) -> str:
    """Вычислить payment_status заявки по сумме оплаченных платежей.

    Приоритет цели: final_amount (факт) > expected_amount (план).
    Если цель не задана — факт наличия хоть какой-то оплаты даёт 'paid'.

    Returns: 'unpaid' | 'partially_paid' | 'paid' | 'overpaid'
    """
    target = final_amount if final_amount is not None else expected_amount

    if paid_total <= Decimal(0):
        return "unpaid"

    if target is None:
        # Нет плановой суммы — любая оплата закрывает долг
        return "paid"

    if paid_total < target:
        return "partially_paid"
    if paid_total > target:
        return "overpaid"
    return "paid"


async def recompute_and_save(db: AsyncSession, order: Order) -> str:
    """Пересчитать payment_status по фактически оплаченным платежам и записать в order.

    Не делает commit — вызывающий код обязан его выполнить (или flush).
    """
    result = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.order_id == order.id,
            Payment.status == PaymentStatus.PAID,
        )
    )
    paid_total = Decimal(str(result.scalar() or 0))

    expected = Decimal(str(order.expected_amount)) if order.expected_amount is not None else None
    final = Decimal(str(order.final_amount)) if order.final_amount is not None else None

    status = compute_payment_status(paid_total, expected, final)
    order.payment_status = status
    log.debug(
        "recompute_and_save: order=%s paid_total=%s expected=%s final=%s → %s",
        order.id, paid_total, expected, final, status,
    )
    return status


async def _generate_invoice_number(db: AsyncSession) -> str:
    """Генерация номера счёта: INV-2026-000001."""
    year = datetime.now(timezone.utc).year
    result = await db.execute(
        select(func.count()).where(Payment.invoice_number.like(f"INV-{year}-%"))
    )
    count = (result.scalar() or 0) + 1
    return f"INV-{year}-{count:06d}"


def _calc_amount(order: Order, basis: str, fuel_coeff: float, delivery_coeff: float) -> float:
    """Рассчитать сумму счёта на основе тарифов клиента."""
    volume = float(order.volume_requested) if basis == "requested" else float(order.volume_delivered or order.volume_requested)
    fuel_price = BASE_FUEL_PRICES.get(order.fuel_type.value if hasattr(order.fuel_type, 'value') else order.fuel_type, 50.0)
    fuel_total = volume * fuel_price * fuel_coeff
    delivery_total = volume * BASE_DELIVERY_PRICE_PER_LITER * delivery_coeff
    return round(fuel_total + delivery_total, 2)


_VALID_BASIS = {"requested", "delivered"}


async def create_invoice(
    db: AsyncSession,
    order_id: uuid.UUID,
    basis: str,  # "requested" | "delivered"
    actor: TokenUser,
    fuel_coeff: float = 1.0,
    delivery_coeff: float = 1.0,
) -> Payment:
    """Создать счёт на оплату. basis='requested' — предоплата, 'delivered' — по факту."""
    if basis not in _VALID_BASIS:
        raise ValidationError(f"basis должен быть одним из: {', '.join(_VALID_BASIS)}")

    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Счёт формирует менеджер или администратор")

    result = await db.execute(select(Order).where(Order.id == order_id, Order.is_archived == False))  # noqa: E712
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена")

    # Предоплату нельзя выставить если заказ уже завершён
    if basis == "requested" and order.status in (
        OrderStatus.DELIVERED, OrderStatus.PARTIALLY_DELIVERED, OrderStatus.CLOSED
    ):
        raise ValidationError("Предоплата не может быть выставлена для завершённой заявки")

    if basis == "delivered" and order.volume_delivered is None:
        raise ValidationError("Фактический объём ещё не зафиксирован — доставка не завершена")

    amount = _calc_amount(order, basis, fuel_coeff, delivery_coeff)
    invoice_number = await _generate_invoice_number(db)

    kind = PaymentKind.PREPAYMENT if basis == "requested" else PaymentKind.ACTUAL

    payment = Payment(
        order_id=order.id,
        client_id=order.client_id,
        kind=kind,
        status=PaymentStatus.PENDING,
        amount=amount,
        invoice_number=invoice_number,
        created_by_id=actor.id,
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)
    return payment


async def record_payment(
    db: AsyncSession,
    order_id: uuid.UUID,
    amount: float,
    method: str,
    actor: TokenUser,
    notes: str | None = None,
) -> Payment:
    """Зафиксировать факт оплаты вручную."""
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Оплату фиксирует менеджер или администратор")

    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise NotFoundError("Заявка не найдена")
    if order.is_archived:
        raise ValidationError("Нельзя фиксировать оплату для архивированной заявки")

    # Ищем pending-счёт для этого заказа; блокируем строку от параллельной оплаты
    pending = await db.execute(
        select(Payment).where(
            Payment.order_id == order_id,
            Payment.status == PaymentStatus.PENDING,
        ).order_by(Payment.created_at.desc()).limit(1).with_for_update()
    )
    pending_payment = pending.scalar_one_or_none()

    if pending_payment:
        pending_payment.status = PaymentStatus.PAID
        pending_payment.paid_at = datetime.now(timezone.utc)
        pending_payment.method = method
        if notes:
            pending_payment.notes = notes
        payment = pending_payment
    else:
        # Нет pending — создаём новую запись об оплате
        payment = Payment(
            order_id=order.id,
            client_id=order.client_id,
            kind=PaymentKind.ACTUAL,
            status=PaymentStatus.PAID,
            method=method,
            amount=amount,
            paid_at=datetime.now(timezone.utc),
            notes=notes,
            created_by_id=actor.id,
        )
        db.add(payment)

    # Пересчитать payment_status по всем оплаченным платежам
    await recompute_and_save(db, order)
    await db.flush()
    await db.refresh(payment)
    log.info("Payment recorded: order=%s amount=%s method=%s actor=%s", order_id, amount, method, actor.id)
    return payment


async def list_payments(
    db: AsyncSession,
    actor: TokenUser,
    *,
    order_id: uuid.UUID | None = None,
    client_id: uuid.UUID | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 100,
) -> list[Payment]:
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError("Список платежей доступен менеджеру и администратору")

    conditions = []
    if order_id:
        conditions.append(Payment.order_id == order_id)
    if client_id:
        conditions.append(Payment.client_id == client_id)
    if status:
        conditions.append(Payment.status == status)
    if date_from:
        conditions.append(Payment.created_at >= date_from)
    if date_to:
        conditions.append(Payment.created_at <= date_to)

    q = select(Payment)
    if conditions:
        q = q.where(and_(*conditions))
    q = q.order_by(Payment.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(q)
    return list(result.scalars().all())


async def payment_report(
    db: AsyncSession,
    actor: TokenUser,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict:
    """Сводный отчёт по оплатам."""
    if actor.role not in (ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError()

    conditions = []
    if date_from:
        conditions.append(Payment.created_at >= date_from)
    if date_to:
        conditions.append(Payment.created_at <= date_to)

    base_q = select(Payment)
    if conditions:
        base_q = base_q.where(and_(*conditions))

    result = await db.execute(base_q)
    payments = result.scalars().all()

    total = sum(float(p.amount) for p in payments)
    paid = sum(float(p.amount) for p in payments if p.status == PaymentStatus.PAID)
    pending = sum(float(p.amount) for p in payments if p.status == PaymentStatus.PENDING)

    return {
        "total_count": len(payments),
        "paid_count": sum(1 for p in payments if p.status == PaymentStatus.PAID),
        "pending_count": sum(1 for p in payments if p.status == PaymentStatus.PENDING),
        "total_amount": total,
        "paid_amount": paid,
        "pending_amount": pending,
    }


def generate_invoice_html(payment: Payment, order: Order, client_info: dict, seller_info: dict) -> str:
    """Генерация HTML-счёта. Возвращается как строка для отображения/печати."""
    fuel_labels = {
        "diesel_summer": "Дизельное топливо летнее (ДТ-Л)",
        "diesel_winter": "Дизельное топливо зимнее (ДТ-З)",
        "petrol_92":     "Бензин АИ-92",
        "petrol_95":     "Бензин АИ-95",
        "fuel_oil":      "Топочный мазут М-100",
    }
    fuel_type = order.fuel_type.value if hasattr(order.fuel_type, 'value') else str(order.fuel_type)
    fuel_name = fuel_labels.get(fuel_type, fuel_type)

    basis_label = "Предоплата" if payment.kind == PaymentKind.PREPAYMENT else "По факту доставки"
    volume = float(order.volume_requested) if payment.kind == PaymentKind.PREPAYMENT else float(order.volume_delivered or order.volume_requested)
    unit_price = round(float(payment.amount) / volume, 2) if volume else 0

    date_str = (payment.created_at or datetime.now(timezone.utc)).strftime("%d.%m.%Y")
    s = seller_info
    client_name = _html.escape(client_info.get("name", "—"))
    client_inn  = _html.escape(client_info.get("inn", "—"))
    client_addr = _html.escape(client_info.get("address", "—"))

    return f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="UTF-8">
<title>Счёт {payment.invoice_number}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 13px; color: #000; margin: 30px; }}
  h2 {{ font-size: 16px; text-align: center; margin-bottom: 4px; }}
  .subtitle {{ text-align: center; font-size: 12px; color: #555; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 14px; }}
  table td, table th {{ border: 1px solid #999; padding: 6px 10px; font-size: 12px; }}
  table th {{ background: #f0f0f0; font-weight: bold; text-align: center; }}
  .requisites {{ display: flex; gap: 40px; margin-bottom: 20px; }}
  .req-block {{ flex: 1; }}
  .req-block b {{ display: block; margin-bottom: 4px; }}
  .total-row td {{ font-weight: bold; background: #f9f9f9; }}
  .sign {{ margin-top: 40px; display: flex; justify-content: space-between; }}
  .sign-line {{ border-bottom: 1px solid #000; width: 200px; margin-top: 20px; }}
</style>
</head><body>
<h2>СЧЁТ НА ОПЛАТУ № {payment.invoice_number} от {date_str}</h2>
<div class="subtitle">{basis_label}</div>

<div class="requisites">
  <div class="req-block">
    <b>Поставщик:</b>
    {s['name']}<br>
    ИНН: {s['inn']} / КПП: {s['kpp']}<br>
    {s['address']}<br>
    Тел.: {s['phone']}
  </div>
  <div class="req-block">
    <b>Покупатель:</b>
    {client_name}<br>
    ИНН: {client_inn}<br>
    {client_addr}
  </div>
</div>

<div class="req-block" style="margin-bottom:14px">
  <b>Банк поставщика:</b> {s['bank']}<br>
  Р/с: {s['rs']} / К/с: {s['ks']} / БИК: {s['bik']}
</div>

<table>
  <tr>
    <th>№</th><th>Наименование</th><th>Кол-во (л)</th>
    <th>Цена (₽/л)</th><th>Сумма (₽)</th>
  </tr>
  <tr>
    <td>1</td>
    <td>{fuel_name}</td>
    <td style="text-align:right">{volume:,.0f}</td>
    <td style="text-align:right">{unit_price:,.2f}</td>
    <td style="text-align:right">{float(payment.amount):,.2f}</td>
  </tr>
  <tr class="total-row">
    <td colspan="4" style="text-align:right">ИТОГО К ОПЛАТЕ:</td>
    <td style="text-align:right">{float(payment.amount):,.2f} ₽</td>
  </tr>
</table>

<p>Заявка: <b>{order.order_number}</b> · Адрес доставки: {order.delivery_address}</p>

<div class="sign">
  <div>Руководитель ________________ <div class="sign-line"></div></div>
  <div>Бухгалтер ________________ <div class="sign-line"></div></div>
</div>
</body></html>"""
