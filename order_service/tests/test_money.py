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
    per_liter_with_delivery,
    round_order_total,
    short_org_name,
    strip_leading_zeros,
)

D = Decimal


# ── round_order_total ─────────────────────────────────────────────────────────

def test_total_is_whole_ruble_and_delivery_absorbs_kopecks():
    # 1234 л × 63.55 − 2% = 76852.286 → 76852.29; доставка юрлица 4000 × 1.22
    fuel = D("76852.29")
    total, delivery = round_order_total(fuel, D("4880.00"))
    assert total == D("81732.00")
    assert delivery == D("4879.71")
    assert fuel + delivery == total


def test_reference_example_1000l_legal_entity():
    # 1000 л × 63.5 − 2% = 62230.00; доставка 4000 ₽ ×1.22 = 4880.00
    fuel = D("62230.00")
    total, delivery = round_order_total(fuel, D("4880.00"))
    assert total == D("67110.00")
    assert delivery == D("4880.00")
    assert fuel + delivery == total


def test_no_delivery_gives_whole_ruble_total():
    total, delivery = round_order_total(D("62230.49"), None)
    assert total == D("62230.00")
    assert delivery is None


def test_no_delivery_rounds_half_up():
    total, delivery = round_order_total(D("62230.50"), None)
    assert total == D("62231.00")
    assert delivery is None


def test_manual_delivery_cost_kept_when_total_already_whole():
    total, delivery = round_order_total(D("62230.00"), D("3500.00"))
    assert total == D("65730.00")
    assert delivery == D("3500.00")


def test_zero_delivery_stays_zero():
    total, delivery = round_order_total(D("100.40"), D("0"))
    assert total == D("100.00")
    assert delivery == D("0.00")


def test_tiny_delivery_absorbed_into_fuel_never_negative():
    # Поправка (−0.40) увела бы доставку в минус — доставка обнуляется.
    total, delivery = round_order_total(D("100.40"), D("0.05"))
    assert total == D("100.00")
    assert delivery == D("0.00")
    assert delivery >= 0


def test_none_fuel_subtotal_passes_through():
    total, delivery = round_order_total(None, D("4000"))
    assert total is None
    assert delivery == D("4000")


def test_accepts_floats_and_strings():
    total, delivery = round_order_total(76852.29, "4880")
    assert total == D("81732.00")
    assert delivery == D("4879.71")


@pytest.mark.parametrize("fuel,dlv", [
    ("1.11", "2.22"), ("999999.99", "0.51"), ("63500.00", "4270.00"),
    ("12345.67", "890.12"), ("0.01", "0.99"),
])
def test_invariant_fuel_plus_delivery_equals_total(fuel, dlv):
    fuel_d = D(fuel)
    total, delivery = round_order_total(fuel_d, D(dlv))
    assert total == total.quantize(D("1"))  # целый рубль
    if delivery and delivery > 0:
        assert fuel_d + delivery == total


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
