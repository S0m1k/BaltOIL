"""Юниты чистых функций округления/коротких имён (без БД и без сервисов).

Запуск из папки order_service:  pytest tests/test_money.py
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.money import (  # noqa: E402
    invoice_display_number,
    order_total,
    per_liter_with_delivery,
    price_first_breakdown,
    short_org_name,
    strip_leading_zeros,
)

D = Decimal


# ── price_first_breakdown ─────────────────────────────────────────────────────

def test_reference_example_593l_from_task():
    # Пример заказчика (CRM-27): 593 л × 90 ₽/л + доставка 3200, НДС 22%.
    bd = price_first_breakdown(D("56570.00"), 593, 22)
    assert bd["unit_no_vat"] == D("78.19")
    assert bd["sum_no_vat"] == D("46366.67")
    assert bd["vat"] == D("10200.67")
    assert bd["total"] == D("56567.34")


def test_price_times_volume_equals_sum():
    bd = price_first_breakdown(D("56570.00"), 593, 22)
    assert bd["unit_no_vat"] * D("593") == bd["sum_no_vat"]
    assert bd["sum_no_vat"] + bd["vat"] == bd["total"]


def test_zero_vat_rate_keeps_total():
    bd = price_first_breakdown(D("1000.00"), 100, 0)
    assert bd["unit_no_vat"] == D("10.00")
    assert bd["vat"] == D("0.00")
    assert bd["total"] == D("1000.00")


def test_breakdown_guards():
    assert price_first_breakdown(None, 100, 22) is None
    assert price_first_breakdown(D("100"), 0, 22) is None
    assert price_first_breakdown(D("100"), None, 22) is None


# ── order_total ───────────────────────────────────────────────────────────────

def test_order_total_matches_invoice_total():
    # Итог заявки обязан совпасть с «Всего к оплате» счёта копейка в копейку.
    total = order_total(D("53370.00"), D("3200.00"), 593, 22)
    assert total == price_first_breakdown(D("56570.00"), 593, 22)["total"]
    assert total == D("56567.34")


def test_order_total_keeps_kopecks():
    # Правило «целыми рублями» (2026-08-24) отменено — копейки сохраняются.
    total = order_total(D("53370.00"), D("3200.00"), 593, 22)
    assert total == D("56567.34")
    assert total != total.quantize(D("1"))


def test_order_total_without_volume_is_plain_sum():
    assert order_total(D("62230.49"), D("3500.00"), None, 22) == D("65730.49")
    assert order_total(D("62230.49"), D("3500.00"), 0, 22) == D("65730.49")


def test_order_total_none_fuel_subtotal():
    assert order_total(None, D("4000"), 100, 22) is None


def test_order_total_accepts_floats_and_strings():
    assert order_total(76852.29, "4880", 1234, 22) == order_total(
        D("76852.29"), D("4880"), 1234, 22
    )


@pytest.mark.parametrize("fuel,dlv,vol", [
    ("1.11", "2.22", 10), ("999999.99", "0.51", 20000), ("63500.00", "4270.00", 1000),
    ("12345.67", "890.12", 593), ("0.01", "0.99", 1),
])
def test_invariant_total_is_reproducible_from_price(fuel, dlv, vol):
    total = order_total(D(fuel), D(dlv), vol, 22)
    bd = price_first_breakdown(total, vol, 22)
    # Пересчёт итога от него самого не «уплывает» — счёт стабилен при перевыпуске.
    assert bd["total"] == total
    assert bd["unit_no_vat"] * D(str(vol)) == bd["sum_no_vat"]


# ── per_liter_with_delivery ───────────────────────────────────────────────────

def test_per_liter_with_delivery():
    assert per_liter_with_delivery(D("67110.00"), 1000) == D("67.11")


def test_per_liter_with_delivery_rounds():
    assert per_liter_with_delivery(D("81732.00"), 1234) == D("66.23")


def test_per_liter_with_delivery_guards():
    assert per_liter_with_delivery(None, 100) is None
    assert per_liter_with_delivery(D("100"), 0) is None
    assert per_liter_with_delivery(D("100"), None) is None


# ── short_org_name ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ('ООО "ОТК"', "ОТК"),
    ("ООО «ОТК»", "ОТК"),
    ("ООО ОТК", "ОТК"),
    ("ОOO", "ОOO"),  # латинские O — не наша форма, оставляем как есть
    ('АО "Лидер-Диз"', "Лидер-Диз"),
    ('ПАО «Газпром нефть»', "Газпром нефть"),
    ("ИП Иванов Иван Иванович", "Иванов Иван Иванович"),
    ("ОП СЗТК", "СЗТК"),
    ('Общество с ограниченной ответственностью "Ромашка"', "Ромашка"),
    ('ООО ТД "Ромашка"', "ТД Ромашка"),
    ("Аорта", "Аорта"),          # не путать с формой «АО»
    ("АОЗТ Ромашка", "АОЗТ Ромашка"),
    ("  ООО   «Тест   Тест»  ", "Тест Тест"),
])
def test_short_org_name(raw, expected):
    assert short_org_name(raw) == expected


def test_short_org_name_empty_result_falls_back_to_full():
    assert short_org_name('ООО ""') == 'ООО ""'
    assert short_org_name("ООО") == "ООО"


def test_short_org_name_none():
    assert short_org_name(None) == ""
    assert short_org_name("") == ""


# ── номера ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("0166", "166"), ("0001", "1"), ("1234", "1234"),
    ("0000", "0"), ("TTN-2026-000001", "TTN-2026-000001"), (None, ""),
])
def test_strip_leading_zeros(raw, expected):
    assert strip_leading_zeros(raw) == expected


def test_invoice_display_number():
    assert invoice_display_number("0166", 'ООО "ОТК"') == "166 ОТК"
    assert invoice_display_number("0166", None) == "166"
    assert invoice_display_number("0166", "   ") == "166"
    assert invoice_display_number("0145", "ИП Петров П.П.") == "145 Петров П.П."
