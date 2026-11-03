"""Формула тарифа с округлением до шага (физлица = юрлица −10%, до 50 копеек)."""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import tariff_formula as tf  # noqa: E402

D = Decimal


def test_minus_10_percent_rounded_to_50_kop():
    # 85 → 76.50 (ровно), 86 → 77.40 → 77.50, 125 → 112.50, 150 → 135
    cases = {"85": "76.5000", "86": "77.5000", "125": "112.5000", "150": "135.0000", "100": "90.0000"}
    for base, want in cases.items():
        assert tf.apply_formula(D(base), tf.FORMULA_PERCENT, D("-10"), D("0.5")) == D(want), base


def test_rounding_is_half_up_to_nearest_step():
    # 77.25 → ровно посередине между 77.00 и 77.50 → вверх
    assert tf.apply_formula(D("85.8333"), tf.FORMULA_PERCENT, D("-10"), D("0.5")) == D("77.5000")
    assert tf.apply_formula(D("84.1"), tf.FORMULA_PERCENT, D("-10"), D("0.5")) == D("75.5000")  # 75.69 → 75.50


def test_no_rounding_by_default_keeps_old_behaviour():
    assert tf.apply_formula(D("86"), tf.FORMULA_PERCENT, D("-10")) == D("77.4000")


def test_derive_rows_passes_round_to():
    rows = tf.derive_price_rows(
        [{"fuel_type": "DT", "price_per_liter": D("86"), "is_hidden": False}],
        [], tf.FORMULA_PERCENT, D("-10"), D("0.5"),
    )
    assert rows[0]["price_per_liter"] == D("77.5000")
