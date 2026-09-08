"""CRM-39: правка заявки в закрытом статусе (доставлена/отменена).

Гейт вынесен в чистую функцию `_check_closed_order_edit` — БД не нужна.

Запуск из папки order_service:  pytest tests/test_closed_order_edit.py
"""
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.dependencies import TokenUser  # noqa: E402
from app.models.order import OrderStatus  # noqa: E402
from app.services.order_service import _check_closed_order_edit  # noqa: E402

CLOSED = [OrderStatus.DELIVERED, OrderStatus.CANCELLED]
OPEN = [OrderStatus.NEW, OrderStatus.AWAITING_MANAGER, OrderStatus.ACCEPTED]


def _actor(role: str) -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


def _order(status: OrderStatus):
    return SimpleNamespace(status=status)


@pytest.mark.parametrize("status", CLOSED)
def test_manager_cannot_edit_closed_order(status):
    with pytest.raises(Exception) as exc:
        _check_closed_order_edit(_order(status), _actor("manager"), {"delivery_address"})
    assert exc.value.status_code == 403
    assert "только администратор" in exc.value.detail


@pytest.mark.parametrize("status", CLOSED)
def test_admin_may_edit_paper_fields_of_closed_order(status):
    _check_closed_order_edit(
        _order(status), _actor("admin"),
        {"delivery_address", "manager_comment", "contact_person_phone"},
    )


@pytest.mark.parametrize("status", CLOSED)
@pytest.mark.parametrize("field", ["fuel_type", "volume_requested"])
def test_admin_cannot_change_volume_or_fuel_of_closed_order(status, field):
    with pytest.raises(Exception) as exc:
        _check_closed_order_edit(_order(status), _actor("admin"), {field})
    assert exc.value.status_code == 422
    assert "Объём и вид топлива" in exc.value.detail


@pytest.mark.parametrize("status", OPEN)
@pytest.mark.parametrize("role", ["manager", "admin"])
def test_open_statuses_are_untouched(status, role):
    _check_closed_order_edit(_order(status), _actor(role), {"fuel_type", "volume_requested"})
