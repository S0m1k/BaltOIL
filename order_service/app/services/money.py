"""Чистые функции денежного округления и коротких имён документов.

Модуль намеренно не импортирует ничего из проекта (только stdlib) — его можно
гонять юнит-тестами без БД и без поднятого сервиса.

Две темы:

1. Итог заявки и счёта (решение заказчика 2026-09-02, CRM-27). Первична ЦЕНА
   ЗА ЛИТР без НДС: её округляют до копейки, а всё остальное считают от неё,
   чтобы в счёте «цена × количество» в точности давало сумму строки. Правило
   «итог целыми рублями» (2026-08-24) отменено — итог хранится с копейками, и
   стоимость доставки больше не «поглощает» копеечный остаток.

2. Короткое имя документа-счёта: «0166» + «ООО "ОТК"» → «166 ОТК».
"""
from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")

# Ставка НДС по умолчанию, если реквизиты продавца не заданы (образец заказчика).
DEFAULT_VAT_RATE = 22

__all__ = [
    "CENT",
    "DEFAULT_VAT_RATE",
    "to_decimal",
    "price_first_breakdown",
    "order_total",
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


def price_first_breakdown(raw_total, volume, vat_rate=DEFAULT_VAT_RATE) -> dict | None:
    """Разложить «грязную» сумму на цену за литр без НДС, базу, налог и итог.

    Первична цена за литр без НДС — она округляется до копейки, остальное
    считается ОТ НЕЁ, поэтому в счёте «цена × количество = сумма» сходится
    в точности (CRM-27, заказчик 2026-09-02).

        unit_no_vat = round(raw_total / (1 + rate/100) / volume, 2)
        sum_no_vat  = round(unit_no_vat × volume, 2)
        vat         = round(sum_no_vat × rate/100, 2)
        total       = sum_no_vat + vat

    Итог поэтому может на копейки отличаться от raw_total — это ожидаемо: и
    сумма заявки, и счёт считаются этой же функцией, так что они совпадают.

    Возвращает {"unit_no_vat", "sum_no_vat", "vat", "total"} (Decimal, 2 знака)
    или None, если сумма не задана либо объём непригоден для деления.
    """
    raw = to_decimal(raw_total)
    vol = to_decimal(volume)
    if raw is None or vol is None or vol <= 0:
        return None

    rate = to_decimal(vat_rate) or Decimal("0")
    divisor = Decimal("1") + rate / Decimal("100")

    unit_no_vat = (raw / divisor / vol).quantize(CENT, rounding=ROUND_HALF_UP)
    sum_no_vat = (unit_no_vat * vol).quantize(CENT, rounding=ROUND_HALF_UP)
    vat = (sum_no_vat * rate / Decimal("100")).quantize(CENT, rounding=ROUND_HALF_UP)
    return {
        "unit_no_vat": unit_no_vat,
        "sum_no_vat":  sum_no_vat,
        "vat":         vat,
        "total":       (sum_no_vat + vat).quantize(CENT),
    }


def order_total(fuel_subtotal, delivery_cost, volume=None, vat_rate=DEFAULT_VAT_RATE):
    """Итог заявки = топливо + доставка, приведённый к цене за литр (2 знака).

    Считается той же функцией, что и счёт (`price_first_breakdown`), поэтому
    «Всего к оплате» в счёте совпадает с `expected_amount`/`final_amount`
    заявки копейка в копейку.

    Без объёма (или при нулевом объёме) цену за литр вывести нельзя — тогда
    возвращается простая сумма с округлением до копейки.

    fuel_subtotal is None → None: топливной части нет, одна доставка за итог
    заявки не выдаётся.
    """
    fuel = to_decimal(fuel_subtotal)
    if fuel is None:
        return None

    delivery = to_decimal(delivery_cost) or Decimal("0")
    raw_total = (fuel + delivery).quantize(CENT, rounding=ROUND_HALF_UP)

    breakdown = price_first_breakdown(raw_total, volume, vat_rate)
    if breakdown is None:
        return raw_total
    return breakdown["total"]


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
