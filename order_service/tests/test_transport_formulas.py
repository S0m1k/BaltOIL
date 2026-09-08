"""Формулы блока «куплено» заявки на перевозку (ТЗ Ирины, макет стр. 3).

Запуск из папки order_service:  pytest tests/test_transport_formulas.py
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.services.transport_formulas import (  # noqa: E402
    DEFAULT_DRIVER_PERCENT, driver_payment, liters_from_kg, purchase_total,
    recompute, supplier_payments_total,
)


# ── кол-во кг × плотность = кол-во литров ─────────────────────────────────────

def test_liters_from_kg_multiplies_by_density():
    assert liters_from_kg(1000, "0.84") == Decimal("840.000")


def test_liters_from_kg_accepts_strings_and_floats():
    assert liters_from_kg("2500", 0.86) == Decimal("2150.000")


@pytest.mark.parametrize("kg,density", [(None, "0.84"), (1000, None), (1000, 0), (1000, -1)])
def test_liters_from_kg_returns_none_when_data_missing_or_impossible(kg, density):
    assert liters_from_kg(kg, density) is None


def test_liters_from_kg_ignores_garbage_input():
    assert liters_from_kg("не число", "0.84") is None


# ── итого, руб = кол-во × стоимость ───────────────────────────────────────────

def test_purchase_total_prefers_kilogram_pair():
    # Пара по кг заполнена целиком — литры игнорируются, даже если тоже заданы
    total = purchase_total(amount_kg=1000, price_per_kg="55.50",
                           amount_l=1190, price_per_l="99")
    assert total == Decimal("55500.00")


def test_purchase_total_falls_back_to_liters_when_kg_pair_incomplete():
    total = purchase_total(amount_kg=1000, price_per_kg=None,
                           amount_l="1190", price_per_l="47.20")
    assert total == Decimal("56168.00")


def test_purchase_total_rounds_to_kopecks():
    assert purchase_total(amount_l=3, price_per_l="10.005") == Decimal("30.02")


def test_purchase_total_returns_none_without_any_complete_pair():
    assert purchase_total(amount_kg=1000, amount_l=1190) is None


# ── водителю = итого × 0,25 ───────────────────────────────────────────────────

def test_driver_payment_defaults_to_25_percent():
    assert DEFAULT_DRIVER_PERCENT == Decimal("25")
    assert driver_payment("100000") == Decimal("25000.00")


def test_driver_payment_honours_custom_percent():
    assert driver_payment("100000", "30") == Decimal("30000.00")


def test_driver_payment_zero_percent_is_not_treated_as_missing():
    # 0 % — осознанный ввод «водителю не платим», не «поле пустое»
    assert driver_payment("100000", 0) == Decimal("0.00")


def test_driver_payment_without_total_is_none():
    assert driver_payment(None, "25") is None


# ── оплаты поставщику ─────────────────────────────────────────────────────────

def test_supplier_payments_total_sums_filled_rows_only():
    rows = [
        {"amount": "10000", "date": "2026-09-01"},
        {"amount": None, "date": None},
        {"amount": "5500.50", "date": "2026-09-05"},
        {},
    ]
    assert supplier_payments_total(rows) == Decimal("15500.50")


def test_supplier_payments_total_of_nothing_is_zero():
    assert supplier_payments_total(None) == Decimal("0.00")
    assert supplier_payments_total([]) == Decimal("0.00")


# ── recompute: ручной ввод побеждает расчёт ───────────────────────────────────

def test_recompute_fills_empty_derived_fields():
    out = recompute({
        "amount_kg": "1000", "density": "0.84",
        "price_per_kg": "50", "amount_l": None,
        "total_amount": None, "driver_payment_amount": None,
        "driver_payment_percent": None,
    })
    assert out["amount_l"] == Decimal("840.000")
    assert out["total_amount"] == Decimal("50000.00")
    assert out["driver_payment_amount"] == Decimal("12500.00")


def test_recompute_never_overwrites_manual_values():
    out = recompute({
        "amount_kg": "1000", "density": "0.84", "price_per_kg": "50",
        "amount_l": Decimal("900"),
        "total_amount": Decimal("1"),
        "driver_payment_amount": Decimal("2"),
        "driver_payment_percent": None,
    })
    assert out["amount_l"] == Decimal("900")
    assert out["total_amount"] == Decimal("1")
    assert out["driver_payment_amount"] == Decimal("2")


def test_recompute_does_not_mutate_input():
    src = {"amount_kg": "1000", "density": "0.84"}
    recompute(src)
    assert src == {"amount_kg": "1000", "density": "0.84"}
