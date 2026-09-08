"""Перевозки в финансовом отчёте: расход и приход (ТЗ Ирины, 09.2026).

У перевозки нет платежей (таблица ``payments``) — её деньги живут в полях
``transport_details``. Поэтому строки отчёта собираются здесь и выводятся
отдельной секцией «Перевозки», помеченной по каждой строке: так суммы
существующего отчёта по платежам не меняются ни на копейку, а перевозки
всё равно попадают в финансы.

По ТЗ:

* «оплаты поставщику» (до 4 пар «сумма + дата») уходят как **РАСХОД**;
* «стоимость доставки» (услуга доставки клиенту) уходит как **ПРИХОД**.

Оплата водителю тоже показывается — отдельной статьёй расхода, чтобы её было
видно в отчёте и не путать с оплатой поставщику.

Модуль чистый: на вход список пар (order, detail), на выход — список словарей
и словарь итогов. Ни БД, ни сети — тестируется юнитом.
"""
from __future__ import annotations

from decimal import Decimal

#: Пометка строк перевозки в финансовом отчёте.
TRANSPORT_LABEL = "Перевозка"

ARTICLE_SUPPLIER = "Оплата поставщику"
ARTICLE_DELIVERY = "Стоимость доставки"
ARTICLE_DRIVER = "Оплата водителю"

DIRECTION_EXPENSE = "expense"
DIRECTION_INCOME = "income"

TRANSPORT_TYPE_RU = {
    "to_base": "Доставка на базу",
    "to_client": "Услуга доставки клиенту",
}


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return None


def _base_row(order, detail) -> dict:
    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "ttn_number": order.ttn_number,
        "transport_type": detail.transport_type,
        "route": order.delivery_address or "",
        "status": getattr(order.status, "value", order.status),
        "created_at": order.created_at,
    }


def rows_for_order(order, detail) -> list[dict]:
    """Финансовые строки одной перевозки: расход поставщику, приход, водитель.

    Нулевые и незаполненные суммы строк не порождают — пустая строка в отчёте
    только мешает сводить итог.
    """
    if detail is None:
        return []

    rows: list[dict] = []

    for payment in detail.supplier_payments or []:
        amount = _dec((payment or {}).get("amount"))
        if amount is None or amount == 0:
            continue
        rows.append({
            **_base_row(order, detail),
            "direction": DIRECTION_EXPENSE,
            "article": ARTICLE_SUPPLIER,
            "amount": amount,
            "paid_at": (payment or {}).get("date"),
            "is_paid": True,
        })

    delivery = _dec(detail.delivery_price)
    if delivery is not None and delivery != 0:
        rows.append({
            **_base_row(order, detail),
            "direction": DIRECTION_INCOME,
            "article": ARTICLE_DELIVERY,
            "amount": delivery,
            "paid_at": None,
            # Галочка «получили оплату» из формы: приход ожидаемый или полученный
            "is_paid": bool(detail.delivery_paid),
        })

    driver = _dec(detail.driver_payment_amount)
    if driver is not None and driver != 0:
        rows.append({
            **_base_row(order, detail),
            "direction": DIRECTION_EXPENSE,
            "article": ARTICLE_DRIVER,
            "amount": driver,
            "paid_at": None,
            "is_paid": False,
        })

    return rows


def build_rows(pairs) -> list[dict]:
    """Строки по списку пар (order, detail), в порядке поступления."""
    out: list[dict] = []
    for order, detail in pairs:
        out.extend(rows_for_order(order, detail))
    return out


def totals(rows) -> dict[str, Decimal]:
    """Итоги секции «Перевозки»: расход, приход и разбивка расхода."""
    supplier = Decimal("0")
    driver = Decimal("0")
    income = Decimal("0")
    income_received = Decimal("0")

    for row in rows or []:
        amount = _dec(row.get("amount")) or Decimal("0")
        if row.get("direction") == DIRECTION_INCOME:
            income += amount
            if row.get("is_paid"):
                income_received += amount
        elif row.get("article") == ARTICLE_DRIVER:
            driver += amount
        else:
            supplier += amount

    return {
        "expense_supplier": supplier,
        "expense_driver": driver,
        "expense_total": supplier + driver,
        "income_total": income,
        "income_received": income_received,
        "balance": income - supplier - driver,
    }
