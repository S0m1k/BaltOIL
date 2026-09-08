"""Гейт отгрузки и дефолтный тип оплаты юрлица (CRM-36, правки 2026-09-02).

Запуск из папки order_service:  pytest tests/test_shipment_allowed.py
"""
import os
import sys
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.models.order import PaymentType  # noqa: E402
from app.schemas.order import OrderCreateRequest  # noqa: E402
from app.services.payment_service import compute_shipment_allowed  # noqa: E402


def order(**over):
    base = {
        "payment_type": PaymentType.PREPAID,
        "payment_status": "unpaid",
        "shipment_override": None,
        "allow_delivery_unpaid": False,
        "expected_amount": Decimal("10000"),
        "final_amount": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("pt", [
    PaymentType.DEBT, PaymentType.TRADE_CREDIT, PaymentType.POSTPAID,
])
def test_credit_payment_types_ship_without_payment(pt):
    """CRM-36: «в долг» у организации не срабатывал — гейт не знал кредитных типов."""
    assert compute_shipment_allowed(order(payment_type=pt), 0.0) is True


@pytest.mark.parametrize("pt", [
    PaymentType.DEBT, PaymentType.TRADE_CREDIT, PaymentType.POSTPAID,
])
def test_manual_hold_still_wins_over_credit(pt):
    o = order(payment_type=pt, shipment_override="hold")
    assert compute_shipment_allowed(o, 0.0) is False


def test_prepaid_unpaid_still_blocked():
    assert compute_shipment_allowed(order(), 0.0) is False


def test_prepaid_paid_allowed():
    assert compute_shipment_allowed(order(payment_status="paid"), 10000.0) is True


def test_on_delivery_allowed():
    assert compute_shipment_allowed(order(payment_type=PaymentType.ON_DELIVERY), 0.0) is True


# ── Дефолтный тип оплаты: «поле не прислано» отличается от «прислан on_delivery» ──

def _req(**over):
    base = {"fuel_type": "DIESEL_SUMMER", "volume_requested": 1000,
            "delivery_address": "СПб, Невский 1"}
    base.update(over)
    return OrderCreateRequest(**base)


def test_payment_type_absent_is_detectable():
    """create_order подставляет DEBT только когда фронт тип оплаты НЕ прислал."""
    assert "payment_type" not in _req().model_fields_set
    assert _req().payment_type == PaymentType.ON_DELIVERY


def test_explicit_payment_type_is_kept():
    req = _req(payment_type="prepaid")
    assert "payment_type" in req.model_fields_set
    assert req.payment_type == PaymentType.PREPAID


def test_explicit_on_delivery_is_not_treated_as_absent():
    assert "payment_type" in _req(payment_type="on_delivery").model_fields_set
