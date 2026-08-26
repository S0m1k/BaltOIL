"""Валидация цен тарифа после правок CRM-33 (без БД).

Обязательны цены только для ВИДИМЫХ видов топлива; скрытые («глазик» выключен)
и не присланные виды цены не требуют. У формульного тарифа своих цен нет вовсе.

Запуск из папки order_service:  pytest tests/test_tariff_validation.py
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Настройки сервиса читаются из окружения на импорте — подставляем заглушки,
# чтобы тест оставался самодостаточным (БД и сеть не используются).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.exceptions import ValidationError  # noqa: E402
from app.services.tariff_service import _validate_fuel_prices  # noqa: E402

D = Decimal


def price(fuel, value=None, hidden=False):
    return {"fuel_type": fuel, "price_per_liter": value, "is_hidden": hidden}


def test_single_visible_fuel_is_enough():
    # Заказчица пользуется только ДТ-Л-К5 — остальные скрыты
    _validate_fuel_prices([
        price("DIESEL_SUMMER", D("60.00")),
        price("PETROL_92", None, hidden=True),
        price("FUEL_OIL", None, hidden=True),
    ])


def test_missing_fuels_are_allowed():
    # Не присланный вид топлива = скрытый, ошибки быть не должно
    _validate_fuel_prices([price("DIESEL_SUMMER", D("60.00"))])


def test_hidden_fuel_may_keep_its_old_price():
    _validate_fuel_prices([
        price("DIESEL_SUMMER", D("60.00")),
        price("PETROL_92", D("55.00"), hidden=True),
    ])


def test_visible_fuel_without_price_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate_fuel_prices([price("DIESEL_SUMMER", None)])
    assert "DIESEL_SUMMER" in str(exc.value.detail)


def test_visible_fuel_with_zero_price_is_rejected():
    with pytest.raises(ValidationError):
        _validate_fuel_prices([price("DIESEL_SUMMER", D("0"))])


def test_all_fuels_hidden_is_rejected():
    with pytest.raises(ValidationError):
        _validate_fuel_prices([
            price("DIESEL_SUMMER", D("60.00"), hidden=True),
            price("PETROL_92", D("55.00"), hidden=True),
        ])


def test_formula_tariff_needs_no_own_prices():
    # Цены формульного тарифа выводятся из базового — проверка цен не применяется
    _validate_fuel_prices([price("DIESEL_SUMMER", None, hidden=True)], is_formula=True)
