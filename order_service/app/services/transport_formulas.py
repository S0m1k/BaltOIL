"""Формулы блока «куплено» заявки на перевозку (ТЗ Ирины, макет стр. 3).

Модуль намеренно чистый: Decimal на входе, Decimal на выходе, никакой БД и
никаких сервисов — значит, проверяется юнит-тестами без поднятого стенда
(tests/test_transport_formulas.py).

Формулы с макета:

* ``кол-во кг × плотность = кол-во литров`` — автозаполнение поля «кол-во, л»;
* ``итого, руб = кол-во × стоимость`` — цена берётся из той пары, что задана
  полностью: сначала килограммы (цена за кг × кг), иначе литры;
* ``водителю = итого × 0,25`` — процент по умолчанию 25, но и процент, и
  саму сумму можно ввести вручную (ручной ввод всегда побеждает расчёт).

Все поля блока 2 по ТЗ необязательны, поэтому каждая формула возвращает
``None``, когда исходных данных не хватает: пустое поле лучше нуля, который
менеджер примет за посчитанный результат.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

#: Процент водителя по умолчанию (поле предзаполнено 25 %).
DEFAULT_DRIVER_PERCENT = Decimal("25")

#: Копейки — все денежные результаты округляем к 2 знакам.
_MONEY_Q = Decimal("0.01")
#: Литры — 3 знака, как в колонке amount_l.
_VOLUME_Q = Decimal("0.001")


def _dec(value) -> Decimal | None:
    """Привести значение к Decimal. None/пустая строка/мусор → None."""
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError, TypeError):
        return None


def _round(value: Decimal | None, quant: Decimal) -> Decimal | None:
    return None if value is None else value.quantize(quant, rounding=ROUND_HALF_UP)


def liters_from_kg(amount_kg, density) -> Decimal | None:
    """Кол-во литров = кол-во кг × плотность.

    Плотность 0 или отрицательная — не физична: считаем данные незаполненными
    и возвращаем None, чтобы не подставлять в форму ноль литров.
    """
    kg = _dec(amount_kg)
    d = _dec(density)
    if kg is None or d is None or d <= 0:
        return None
    return _round(kg * d, _VOLUME_Q)


def purchase_total(
    amount_kg=None,
    amount_l=None,
    price_per_kg=None,
    price_per_l=None,
) -> Decimal | None:
    """Итого, руб = кол-во × стоимость.

    Приоритет у пары «килограммы»: цена за кг — исходная цена закупки у
    поставщика, литры на макете считаются из неё через плотность. Если пара по
    килограммам заполнена не полностью — считаем по литрам. Если ни одна пара
    не заполнена целиком — None.
    """
    kg, p_kg = _dec(amount_kg), _dec(price_per_kg)
    if kg is not None and p_kg is not None:
        return _round(kg * p_kg, _MONEY_Q)

    liters, p_l = _dec(amount_l), _dec(price_per_l)
    if liters is not None and p_l is not None:
        return _round(liters * p_l, _MONEY_Q)

    return None


def driver_payment(total, percent=None) -> Decimal | None:
    """Оплата водителю = итого × процент / 100 (по умолчанию 25 %)."""
    total_dec = _dec(total)
    if total_dec is None:
        return None
    pct = _dec(percent)
    if pct is None:
        pct = DEFAULT_DRIVER_PERCENT
    return _round(total_dec * pct / Decimal("100"), _MONEY_Q)


def supplier_payments_total(payments) -> Decimal:
    """Сумма всех оплат поставщику (до 4 пар «сумма + дата»).

    Строки без суммы пропускаются — в форме заполняют не все четыре пары.
    Возвращаем 0, а не None: это агрегат для отчёта, «нет оплат» = ноль расхода.
    """
    total = Decimal("0")
    for row in payments or []:
        amount = _dec((row or {}).get("amount") if isinstance(row, dict) else row)
        if amount is not None:
            total += amount
    return _round(total, _MONEY_Q) or Decimal("0.00")


def recompute(detail_values: dict) -> dict:
    """Досчитать производные поля блока «куплено» по введённым.

    Возвращает НОВЫЙ словарь (исходный не мутируем): ручной ввод всегда
    приоритетнее расчёта, поэтому заполняются только пустые поля.
    """
    out = dict(detail_values)

    if out.get("amount_l") in (None, ""):
        computed_l = liters_from_kg(out.get("amount_kg"), out.get("density"))
        if computed_l is not None:
            out["amount_l"] = computed_l

    if out.get("total_amount") in (None, ""):
        out["total_amount"] = purchase_total(
            amount_kg=out.get("amount_kg"),
            amount_l=out.get("amount_l"),
            price_per_kg=out.get("price_per_kg"),
            price_per_l=out.get("price_per_l"),
        )

    if out.get("driver_payment_amount") in (None, ""):
        out["driver_payment_amount"] = driver_payment(
            out.get("total_amount"), out.get("driver_payment_percent")
        )

    return out
