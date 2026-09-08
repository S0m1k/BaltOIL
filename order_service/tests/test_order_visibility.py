"""Условия выборки заявок: видимость по роли + фильтр по виду (правки 2026-09-02).

Проверяем скомпилированный SQL-фрагмент — БД и сервисы не нужны.

Запуск из папки order_service:  pytest tests/test_order_visibility.py
"""
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.dependencies import TokenUser  # noqa: E402
from app.models.order import OrderKind  # noqa: E402
from app.services.order_service import _visibility_conditions  # noqa: E402


def _actor(role: str) -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


def _sql(conditions) -> str:
    return " ".join(
        str(c.compile(compile_kwargs={"literal_binds": True})) for c in conditions
    )


@pytest.mark.parametrize("role", ["admin", "manager", "client", "driver"])
def test_kind_filter_applies_for_every_role(role):
    sql = _sql(_visibility_conditions(_actor(role), None, OrderKind.COMPANY))
    assert "order_kind" in sql
    assert "COMPANY" in sql.upper()


@pytest.mark.parametrize("role", ["admin", "manager", "client", "driver"])
def test_without_kind_no_kind_equality(role):
    sql = _sql(_visibility_conditions(_actor(role), None))
    # У водителя order_kind фигурирует в его собственном условии видимости
    # (свободные NEW не бывают ТТН-Л) — но именно как «!=», не как фильтр.
    assert "orders.order_kind = " not in sql


def test_kind_filter_does_not_replace_visibility_of_client():
    actor = _actor("client")
    sql = _sql(_visibility_conditions(actor, None, OrderKind.INDIVIDUAL))
    assert "client_id" in sql
    assert "is_archived" in sql


def test_ttn_l_filter_for_driver_keeps_own_orders_condition():
    sql = _sql(_visibility_conditions(_actor("driver"), None, OrderKind.TTN_L))
    assert "driver_id" in sql
    assert "TTN_L" in sql.upper()
