"""Чистые функции тарифных формул и диффа цен (без БД — легко тестируются).

Правки CRM-33/CRM-32 (2026-08-26):

1. «Глазик» — вид топлива в тарифе можно скрыть (is_hidden). Скрытые виды
   не требуют цены и не предлагаются клиенту при заказе по этому тарифу.
2. Формульный тариф — кастомный тариф может считаться от базового:
   наценка/скидка в % (`percent`) или в ₽/л (`fixed`). Значение знаковое:
   +5 = наценка, −5 = скидка. Пересчёт делается ПРИ ЧТЕНИИ, поэтому смена
   цен базового тарифа автоматически двигает все формульные.
3. История цен — дифф «было → стало» для журнала tariff_price_history.
"""
from decimal import Decimal, ROUND_HALF_UP

FORMULA_PERCENT = "percent"
FORMULA_FIXED = "fixed"
# «= базовый» (CRM-40): цены базового тарифа один-в-один, величина не нужна.
# Нужен, чтобы держать отдельный тариф (свой глазик, свой client_type) без
# наценки — раньше для этого приходилось ставить +0%.
FORMULA_EQUAL = "equal"
VALID_FORMULA_TYPES = (FORMULA_PERCENT, FORMULA_FIXED, FORMULA_EQUAL)

# Цена за литр не может опуститься до нуля даже при агрессивной скидке.
MIN_PRICE = Decimal("0.0001")
_PRICE_Q = Decimal("0.0001")

# Виды изменений в журнале цен
CHANGE_ADDED = "added"
CHANGE_PRICE = "price"
CHANGE_REMOVED = "removed"
CHANGE_HIDDEN = "hidden"
CHANGE_SHOWN = "shown"


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def apply_formula(base_price, formula_type: str | None, formula_value) -> Decimal:
    """Цена формульного тарифа от цены базового.

    percent: base × (1 + value/100);  fixed: base + value;  equal: база как есть.
    value знаковое (+наценка / −скидка). Результат не опускается ниже MIN_PRICE.
    """
    price = _dec(base_price)
    if formula_type == FORMULA_EQUAL:
        # Величина у «= базовый» не хранится, а присланную игнорируем.
        return price.quantize(_PRICE_Q, rounding=ROUND_HALF_UP)
    if formula_type is None or formula_value is None:
        return price.quantize(_PRICE_Q, rounding=ROUND_HALF_UP)
    val = _dec(formula_value)
    if formula_type == FORMULA_PERCENT:
        price = price * (Decimal("1") + val / Decimal("100"))
    elif formula_type == FORMULA_FIXED:
        price = price + val
    else:
        raise ValueError(f"Неизвестный тип формулы: {formula_type}")
    price = price.quantize(_PRICE_Q, rounding=ROUND_HALF_UP)
    return price if price >= MIN_PRICE else MIN_PRICE


def formula_label(formula_type: str | None, formula_value) -> str:
    """Человекочитаемое описание формулы для UI/журнала."""
    if formula_type == FORMULA_EQUAL:
        return "= базовый"
    if formula_type is None or formula_value is None:
        return ""
    val = _dec(formula_value)
    sign = "+" if val >= 0 else "−"
    body = abs(val).normalize()
    unit = "%" if formula_type == FORMULA_PERCENT else " ₽/л"
    return f"{sign}{body}{unit}"


def normalize_rows(rows) -> list[dict]:
    """Привести список цен (ORM-объекты или dict) к единому виду.

    Возвращает [{fuel_type: UPPER, price_per_liter: Decimal|None, is_hidden: bool}].
    """
    out: list[dict] = []
    for row in rows or []:
        if isinstance(row, dict):
            fuel = row.get("fuel_type")
            price = row.get("price_per_liter")
            hidden = bool(row.get("is_hidden", False))
        else:
            fuel = getattr(row, "fuel_type", None)
            price = getattr(row, "price_per_liter", None)
            hidden = bool(getattr(row, "is_hidden", False))
        if not fuel:
            continue
        out.append({
            "fuel_type": str(fuel).upper(),
            "price_per_liter": None if price is None else _dec(price),
            "is_hidden": hidden,
        })
    return out


def derive_price_rows(
    base_rows,
    own_rows,
    formula_type: str | None,
    formula_value,
) -> list[dict]:
    """Эффективные цены формульного тарифа.

    Набор видов топлива берётся из ВИДИМЫХ цен базового тарифа; собственные
    строки формульного тарифа несут только флаг is_hidden (пер-тарифный глазик).
    """
    own_hidden = {
        r["fuel_type"] for r in normalize_rows(own_rows) if r["is_hidden"]
    }
    result: list[dict] = []
    for row in normalize_rows(base_rows):
        if row["is_hidden"] or row["price_per_liter"] is None:
            continue
        result.append({
            "fuel_type": row["fuel_type"],
            "price_per_liter": apply_formula(
                row["price_per_liter"], formula_type, formula_value
            ),
            "is_hidden": row["fuel_type"] in own_hidden,
        })
    return result


def visible_prices(rows) -> dict[str, Decimal]:
    """{FUEL_TYPE: цена} только по видимым видам с заданной ценой."""
    return {
        r["fuel_type"]: r["price_per_liter"]
        for r in normalize_rows(rows)
        if not r["is_hidden"] and r["price_per_liter"] is not None
    }


def diff_price_rows(before, after) -> list[dict]:
    """Дифф для журнала цен: [{fuel_type, change_kind, old_price, new_price}].

    Порядок — по коду топлива, чтобы записи журнала были предсказуемы.
    """
    old = {r["fuel_type"]: r for r in normalize_rows(before)}
    new = {r["fuel_type"]: r for r in normalize_rows(after)}
    changes: list[dict] = []

    for fuel in sorted(set(old) | set(new)):
        o, n = old.get(fuel), new.get(fuel)
        if o is None:
            changes.append({
                "fuel_type": fuel,
                "change_kind": CHANGE_ADDED,
                "old_price": None,
                "new_price": n["price_per_liter"],
            })
            continue
        if n is None:
            changes.append({
                "fuel_type": fuel,
                "change_kind": CHANGE_REMOVED,
                "old_price": o["price_per_liter"],
                "new_price": None,
            })
            continue
        if o["price_per_liter"] != n["price_per_liter"]:
            changes.append({
                "fuel_type": fuel,
                "change_kind": CHANGE_PRICE,
                "old_price": o["price_per_liter"],
                "new_price": n["price_per_liter"],
            })
        if o["is_hidden"] != n["is_hidden"]:
            changes.append({
                "fuel_type": fuel,
                "change_kind": CHANGE_HIDDEN if n["is_hidden"] else CHANGE_SHOWN,
                "old_price": o["price_per_liter"],
                "new_price": n["price_per_liter"],
            })
    return changes
