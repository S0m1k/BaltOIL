"""Юниты формул тарифов, «глазика» и диффа истории цен (без БД и без сервисов).

Запуск из папки order_service:  pytest tests/test_tariff_formula.py
"""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tariff_formula import (  # noqa: E402
    CHANGE_ADDED,
    CHANGE_HIDDEN,
    CHANGE_PRICE,
    CHANGE_REMOVED,
    CHANGE_SHOWN,
    FORMULA_EQUAL,
    MIN_PRICE,
    apply_formula,
    derive_price_rows,
    diff_price_rows,
    formula_label,
    normalize_rows,
    visible_prices,
)

D = Decimal


def row(fuel, price=None, hidden=False):
    return {"fuel_type": fuel, "price_per_liter": None if price is None else D(price),
            "is_hidden": hidden}


# ── apply_formula ─────────────────────────────────────────────────────────────

def test_percent_markup_adds_to_base_price():
    assert apply_formula(D("60.00"), "percent", D("5")) == D("63.0000")


def test_percent_discount_is_negative_value():
    assert apply_formula(D("60.00"), "percent", D("-10")) == D("54.0000")


def test_fixed_markup_is_rubles_per_liter():
    assert apply_formula(D("60.00"), "fixed", D("1.5")) == D("61.5000")


def test_fixed_discount_subtracts():
    assert apply_formula(D("60.00"), "fixed", D("-2.25")) == D("57.7500")


def test_no_formula_returns_base_price():
    assert apply_formula(D("60.00"), None, None) == D("60.0000")


def test_price_never_drops_below_minimum():
    assert apply_formula(D("10.00"), "fixed", D("-999")) == MIN_PRICE
    assert apply_formula(D("10.00"), "percent", D("-100")) == MIN_PRICE


def test_result_is_rounded_to_four_decimals():
    # 63.333333... → 63.3333
    assert apply_formula(D("57.00"), "percent", D("11.111")) == D("63.3333")


def test_equal_formula_keeps_base_price(): # CRM-40
    assert apply_formula(D("60.00"), FORMULA_EQUAL, None) == D("60.0000")


def test_equal_formula_ignores_value():
    """Величина у «= базовый» не хранится, а присланную игнорируем."""
    assert apply_formula(D("60.00"), FORMULA_EQUAL, D("5")) == D("60.0000")


def test_equal_formula_derives_whole_price_list():
    base = [row("DT", "60.00"), row("AI92", "55.50"), row("AI95", None)]
    derived = derive_price_rows(base, [], FORMULA_EQUAL, None)
    assert {r["fuel_type"]: r["price_per_liter"] for r in derived} == {
        "DT": D("60.0000"), "AI92": D("55.5000"),
    }


def test_unknown_formula_type_raises():
    with pytest.raises(ValueError):
        apply_formula(D("60.00"), "magic", D("5"))


def test_formula_label_is_human_readable():
    assert formula_label("percent", D("5")) == "+5%"
    assert formula_label("percent", D("-7.5")) == "−7.5%"
    assert formula_label("fixed", D("2")) == "+2 ₽/л"
    assert formula_label(None, None) == ""
    assert formula_label(FORMULA_EQUAL, None) == "= базовый"


# ── normalize_rows / visible_prices («глазик») ────────────────────────────────

def test_normalize_uppercases_codes_and_defaults_hidden_to_false():
    out = normalize_rows([{"fuel_type": "diesel_summer", "price_per_liter": "60.5"}])
    assert out == [{"fuel_type": "DIESEL_SUMMER", "price_per_liter": D("60.5"),
                    "is_hidden": False}]


def test_normalize_accepts_orm_like_objects():
    class FP:
        fuel_type = "PETROL_92"
        price_per_liter = D("58")
        is_hidden = True

    assert normalize_rows([FP()])[0]["is_hidden"] is True


def test_hidden_fuel_is_not_available_for_ordering():
    rows = [row("DIESEL_SUMMER", "60"), row("PETROL_92", "58", hidden=True)]
    assert visible_prices(rows) == {"DIESEL_SUMMER": D("60")}


def test_visible_fuel_without_price_is_skipped():
    assert visible_prices([row("FUEL_OIL", None)]) == {}


# ── derive_price_rows (формульный тариф) ─────────────────────────────────────

def test_formula_tariff_derives_all_visible_base_fuels():
    base = [row("DIESEL_SUMMER", "60"), row("PETROL_92", "50")]
    out = derive_price_rows(base, [], "percent", D("10"))
    assert visible_prices(out) == {"DIESEL_SUMMER": D("66.0000"),
                                   "PETROL_92": D("55.0000")}


def test_formula_tariff_skips_fuels_hidden_in_base():
    base = [row("DIESEL_SUMMER", "60"), row("PETROL_92", "50", hidden=True)]
    out = derive_price_rows(base, [], "fixed", D("1"))
    assert [r["fuel_type"] for r in out] == ["DIESEL_SUMMER"]


def test_formula_tariff_own_hidden_flag_wins_over_base():
    base = [row("DIESEL_SUMMER", "60"), row("PETROL_92", "50")]
    own = [row("PETROL_92", None, hidden=True)]
    out = derive_price_rows(base, own, "percent", D("0"))
    assert visible_prices(out) == {"DIESEL_SUMMER": D("60.0000")}


def test_base_price_change_propagates_on_read():
    # Правка цены базового тарифа автоматически двигает формульный
    before = derive_price_rows([row("DIESEL_SUMMER", "60")], [], "percent", D("5"))
    after = derive_price_rows([row("DIESEL_SUMMER", "70")], [], "percent", D("5"))
    assert visible_prices(before)["DIESEL_SUMMER"] == D("63.0000")
    assert visible_prices(after)["DIESEL_SUMMER"] == D("73.5000")


# ── diff_price_rows (история цен, CRM-32) ────────────────────────────────────

def test_new_tariff_logs_every_fuel_as_added():
    changes = diff_price_rows([], [row("DIESEL_SUMMER", "60")])
    assert changes == [{"fuel_type": "DIESEL_SUMMER", "change_kind": CHANGE_ADDED,
                        "old_price": None, "new_price": D("60")}]


def test_price_change_records_old_and_new():
    changes = diff_price_rows([row("DIESEL_SUMMER", "60")], [row("DIESEL_SUMMER", "62.5")])
    assert changes == [{"fuel_type": "DIESEL_SUMMER", "change_kind": CHANGE_PRICE,
                        "old_price": D("60"), "new_price": D("62.5")}]


def test_unchanged_price_writes_nothing():
    assert diff_price_rows([row("PETROL_95", "70")], [row("PETROL_95", "70")]) == []


def test_hiding_and_showing_are_logged():
    hidden = diff_price_rows([row("PETROL_95", "70")], [row("PETROL_95", "70", hidden=True)])
    assert [c["change_kind"] for c in hidden] == [CHANGE_HIDDEN]
    shown = diff_price_rows([row("PETROL_95", "70", hidden=True)], [row("PETROL_95", "70")])
    assert [c["change_kind"] for c in shown] == [CHANGE_SHOWN]


def test_removed_fuel_is_logged():
    changes = diff_price_rows([row("FUEL_OIL", "40")], [])
    assert changes[0]["change_kind"] == CHANGE_REMOVED
    assert changes[0]["old_price"] == D("40")


def test_price_and_visibility_change_produce_two_records():
    changes = diff_price_rows(
        [row("DIESEL_WINTER", "65")],
        [row("DIESEL_WINTER", "68", hidden=True)],
    )
    assert [c["change_kind"] for c in changes] == [CHANGE_PRICE, CHANGE_HIDDEN]


def test_changes_are_sorted_by_fuel_code():
    changes = diff_price_rows(
        [row("PETROL_92", "50"), row("DIESEL_SUMMER", "60")],
        [row("PETROL_92", "51"), row("DIESEL_SUMMER", "61")],
    )
    assert [c["fuel_type"] for c in changes] == ["DIESEL_SUMMER", "PETROL_92"]
