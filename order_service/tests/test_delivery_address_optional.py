"""CRM-37: адрес доставки обязателен только клиенту (правки 2026-09-02).

Проверяем чистую функцию нормализации — БД и auth_service не нужны.

Запуск из папки order_service:  pytest tests/test_delivery_address_optional.py
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
from app.services.order_service import _normalize_delivery_address  # noqa: E402


def _actor(role: str) -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


@pytest.mark.parametrize("empty", [None, "", "   ", "\n\t"])
def test_client_must_provide_address(empty):
    with pytest.raises(Exception) as exc:
        _normalize_delivery_address(empty, _actor("client"))
    assert exc.value.status_code == 422
    assert exc.value.detail == "Укажите адрес доставки"


@pytest.mark.parametrize("role", ["manager", "admin", "driver"])
@pytest.mark.parametrize("empty", [None, "", "   "])
def test_staff_and_driver_may_leave_address_empty(role, empty):
    assert _normalize_delivery_address(empty, _actor(role)) == ""


@pytest.mark.parametrize("role", ["client", "manager", "admin", "driver"])
def test_address_is_trimmed_for_everyone(role):
    assert _normalize_delivery_address("  СПб, Невский 1  ", _actor(role)) == "СПб, Невский 1"
