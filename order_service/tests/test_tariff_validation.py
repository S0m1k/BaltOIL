"""Валидация цен тарифа после правок CRM-33 (без БД).

Обязательны цены только для ВИДИМЫХ видов топлива; скрытые («глазик» выключен)
и не присланные виды цены не требуют. У формульного тарифа своих цен нет вовсе.

Запуск из папки order_service:  pytest tests/test_tariff_validation.py
"""
import asyncio
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Настройки сервиса читаются из окружения на импорте — подставляем заглушки,
# чтобы тест оставался самодостаточным (БД и сеть не используются).
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.exceptions import ValidationError  # noqa: E402
from app.services.tariff_service import (  # noqa: E402
    _validate_fuel_prices,
    _validate_formula,
)

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


# ── связка «формульный тариф → базовый» (CRM-33 + «= базовый» CRM-40) ─────────

class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeDB:
    """Возвращает один и тот же базовый тариф на любой запрос."""

    def __init__(self, base):
        self._base = base

    async def execute(self, *args, **kwargs):
        return _FakeResult(self._base)


def _validate(formula_type, formula_value):
    base = SimpleNamespace(is_archived=False, base_tariff_id=None)
    return asyncio.run(_validate_formula(
        _FakeDB(base), uuid.uuid4(), formula_type, formula_value
    ))


def test_equal_formula_needs_no_value():
    _validate("equal", None)


def test_percent_formula_still_needs_value():
    with pytest.raises(ValidationError):
        _validate("percent", None)


def test_unknown_formula_type_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate("magic", D("5"))
    assert "equal" in exc.value.detail
