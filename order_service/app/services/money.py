"""Чистые функции денежного округления и коротких имён документов.

Модуль намеренно не импортирует ничего из проекта (только stdlib) — его можно
гонять юнит-тестами без БД и без поднятого сервиса.

Две темы:

1. Округление итога заявки (решение заказчика 2026-08-24). Итог заявки
   (топливо + доставка) показывается и хранится в ЦЕЛЫХ РУБЛЯХ. Позиции топлива
   считаются по тарифу с копейками, а копеечный остаток гасится в строке
   доставки — так «топливо + доставка = итог» сходится копейка в копейку.
   Если доставки нет (или она полностью съедена поправкой) — итог просто целый
   рубль от суммы топлива, а в счёте строка топлива подгоняется под итог.

2. Короткое имя документа-счёта: «0166» + «ООО "ОТК"» → «166 ОТК».
"""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")
RUBLE = Decimal("1")

__all__ = [
    "CENT",
    "RUBLE",
    "to_decimal",
    "round_order_total",
    "per_liter_with_delivery",
    "short_org_name",
    "strip_leading_zeros",
    "invoice_display_number",
]


def to_decimal(value) -> Decimal | None:
    """Аккуратно привести число/строку/Decimal к Decimal. None → None."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_order_total(fuel_subtotal, delivery_cost):
    """Итог заявки целыми рублями; копейки гасятся в стоимости доставки.

    Возвращает кортеж (total, delivery_adjusted):
      * total — Decimal с двумя знаками, но всегда целое число рублей
        (ROUND_HALF_UP от «топливо + доставка»);
      * delivery_adjusted — стоимость доставки, скорректированная так, что
        fuel_subtotal + delivery_adjusted == total. None, если доставки нет.

    Если доставка задана, но поправка увела бы её в ноль или минус — доставка
    становится 0.00, а весь итог ложится на топливо (в счёте строка топлива
    подгоняется по сумме).

    fuel_subtotal is None → (None, delivery_cost без изменений): суммы нет,
    считать нечего.
    """
    fuel = to_decimal(fuel_subtotal)
    if fuel is None:
        return None, to_decimal(delivery_cost)

    fuel = fuel.quantize(CENT, rounding=ROUND_HALF_UP)
    delivery = to_decimal(delivery_cost)
    if delivery is not None:
        delivery = delivery.quantize(CENT, rounding=ROUND_HALF_UP)

    raw_total = fuel + (delivery or Decimal("0"))
    total = raw_total.quantize(RUBLE, rounding=ROUND_HALF_UP).quantize(CENT)

    if delivery is None:
        return total, None

    adjusted = (total - fuel).quantize(CENT)
    if adjusted <= 0:
        return total, Decimal("0.00")
    return total, adjusted


def per_liter_with_delivery(total, volume) -> Decimal | None:
    """Справочная цена за литр С УЧЁТОМ доставки = итог / литры (2 знака)."""
    total_d = to_decimal(total)
    volume_d = to_decimal(volume)
    if total_d is None or volume_d is None or volume_d <= 0:
        return None
    return (total_d / volume_d).quantize(CENT, rounding=ROUND_HALF_UP)


# ── Короткое имя организации ──────────────────────────────────────────────────

# Кавычки всех сортов, встречающиеся в реквизитах.
_QUOTES = "«»\"'`“”„‟‘’‹›"

# Организационно-правовые формы, отбрасываемые из НАЧАЛА имени.
# Порядок важен только по длине — сортируем ниже, чтобы «АО» не съело
# «Акционерное общество» раньше времени.
_LEGAL_FORMS = (
    "общество с ограниченной ответственностью",
    "непубличное акционерное общество",
    "публичное акционерное общество",
    "закрытое акционерное общество",
    "открытое акционерное общество",
    "акционерное общество",
    "индивидуальный предприниматель",
    "обособленное подразделение",
    "крестьянское фермерское хозяйство",
    "производственный кооператив",
    "ооо", "оао", "зао", "пао", "нао", "ао", "ип", "оп",
    "ано", "нко", "кфх", "муп", "гуп", "фгуп", "мбу", "гбу", "пк", "тсж", "снт",
)
_LEGAL_FORMS_SORTED = tuple(sorted(_LEGAL_FORMS, key=len, reverse=True))

# Символы, которые могут стоять между формой и названием.
_SEPARATORS = " \t .,:-–—" + _QUOTES

_MAX_FORM_STRIPS = 3


def _strip_edges(value: str) -> str:
    """Обрезать мусор СЛЕВА (кавычки/пробелы/тире после формы).

    Справа не трогаем — там могут стоять значащие точки инициалов
    («ИП Петров П.П.»); лишние кавычки всё равно вычищаются посимвольно ниже.
    """
    return value.lstrip(_SEPARATORS)


def short_org_name(full_name: str | None) -> str:
    """'ООО "ОТК"' → 'ОТК'; 'ИП Иванов И.И.' → 'Иванов И.И.'.

    Убирает организационно-правовую форму в начале, кавычки любого вида и
    схлопывает пробелы. Если после чистки ничего не осталось — возвращает
    исходное имя (без изменений, только обрезка пробелов).
    """
    if not full_name:
        return ""
    original = " ".join(str(full_name).split())
    if not original:
        return ""

    result = original
    for _ in range(_MAX_FORM_STRIPS):
        candidate = _strip_edges(result)
        lowered = candidate.lower()
        matched = None
        for form in _LEGAL_FORMS_SORTED:
            if not lowered.startswith(form):
                continue
            rest = candidate[len(form):]
            # Граница слова: за формой должен идти конец строки или не-буква.
            if rest and (rest[0].isalpha() or rest[0].isdigit()):
                continue
            matched = rest
            break
        if matched is None:
            result = candidate
            break
        result = matched

    # Кавычки могут стоять и внутри («Торговый дом "Ромашка"») — чистим целиком.
    cleaned = "".join(ch for ch in result if ch not in _QUOTES)
    cleaned = " ".join(cleaned.split()).lstrip(" \t.,:-–—").strip()
    return cleaned or original


def strip_leading_zeros(doc_number: str | None) -> str:
    """'0166' → '166'. Не-цифровые номера возвращаются как есть."""
    if not doc_number:
        return ""
    value = str(doc_number).strip()
    if not value.isdigit():
        return value
    return value.lstrip("0") or "0"


def invoice_display_number(doc_number: str | None, buyer_name: str | None) -> str:
    """'0166' + 'ООО "ОТК"' → '166 ОТК'.

    Используется как отображаемое имя счёта: файл на диске, вложение письма,
    подпись в чате и в списках документов. Официальный номер ВНУТРИ PDF
    остаётся прежним ('0166') — его этот хелпер не трогает.
    """
    number = strip_leading_zeros(doc_number)
    short = short_org_name(buyer_name)
    if not short:
        return number
    if not number:
        return short
    return f"{number} {short}"
