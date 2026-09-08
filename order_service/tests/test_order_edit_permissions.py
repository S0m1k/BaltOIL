"""CRM-45/CRM-39: кто какие поля заявки может править.

Гейт вынесен в чистую функцию `_check_edit_permissions` — БД не нужна.

Запуск из папки order_service:  pytest tests/test_order_edit_permissions.py
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
from app.services.order_service import _check_edit_permissions  # noqa: E402

CLIENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DRIVER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

OPEN = [OrderStatus.NEW, OrderStatus.AWAITING_MANAGER, OrderStatus.ACCEPTED]
CLOSED = [OrderStatus.DELIVERED, OrderStatus.CANCELLED]

# Поля, которые заказчица просила открыть админу и водителю (CRM-45)
CRM45_FIELDS = ["contact_person_name", "contact_person_phone",
                "delivery_address", "client_comment"]


def _actor(role: str, user_id: uuid.UUID | None = None) -> TokenUser:
    return TokenUser(id=user_id or uuid.uuid4(), role=role, token="t")


def _order(status=OrderStatus.ACCEPTED):
    return SimpleNamespace(status=status, client_id=CLIENT_ID, driver_id=DRIVER_ID)


# ── водитель ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", CRM45_FIELDS + ["manager_comment"])
def test_driver_may_edit_contact_address_and_comments(field):
    _check_edit_permissions(_order(), _actor("driver", DRIVER_ID), {field})


@pytest.mark.parametrize("field", ["expected_amount", "final_amount", "delivery_cost",
                                   "organization_id", "allow_delivery_unpaid"])
def test_driver_cannot_touch_money_or_customer(field):
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(), _actor("driver", DRIVER_ID), {field})
    assert exc.value.status_code == 403


def test_driver_cannot_edit_someone_elses_order():
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(), _actor("driver"), {"client_comment"})
    assert exc.value.status_code == 403
    assert "назначенную вам" in exc.value.detail


@pytest.mark.parametrize("status", CLOSED)
def test_driver_cannot_edit_closed_order(status):
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(status), _actor("driver", DRIVER_ID),
                                {"client_comment"})
    assert exc.value.status_code == 422


# ── клиент ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("field", CRM45_FIELDS)
def test_client_may_edit_own_contact_and_address(field):
    _check_edit_permissions(_order(), _actor("client", CLIENT_ID), {field})


def test_client_cannot_edit_internal_manager_comment():
    # CRM-41: внутренний комментарий клиенту не показывается и не правится
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(), _actor("client", CLIENT_ID), {"manager_comment"})
    assert exc.value.status_code == 403


def test_client_cannot_edit_someone_elses_order():
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(), _actor("client"), {"delivery_address"})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("status", CLOSED)
def test_client_cannot_edit_closed_order(status):
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(status), _actor("client", CLIENT_ID),
                                {"delivery_address"})
    assert exc.value.status_code == 422


# ── staff ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("status", OPEN)
@pytest.mark.parametrize("role", ["manager", "admin"])
def test_staff_edits_everything_in_open_statuses(status, role):
    _check_edit_permissions(
        _order(status), _actor(role),
        {"volume_requested", "expected_amount", "manager_comment", "organization_id"},
    )


@pytest.mark.parametrize("status", CLOSED)
def test_admin_edits_closed_order_but_manager_does_not(status):
    # CRM-39: закрытую заявку доводит до ума только админ
    _check_edit_permissions(_order(status), _actor("admin"), set(CRM45_FIELDS))
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(status), _actor("manager"), set(CRM45_FIELDS))
    assert exc.value.status_code == 403


def test_unknown_role_is_rejected():
    with pytest.raises(Exception) as exc:
        _check_edit_permissions(_order(), _actor("accountant"), {"client_comment"})
    assert exc.value.status_code == 403
