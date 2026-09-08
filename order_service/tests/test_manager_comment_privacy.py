"""CRM-41: комментарий менеджера — внутренний, клиенту не отдаётся.

Проверяем единственное место обрезки ответа под роль — `_hide_internal`
роутера заявок. БД и сервисы не нужны.

Запуск из папки order_service:  pytest tests/test_manager_comment_privacy.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.dependencies import TokenUser  # noqa: E402
from app.models.order import OrderKind, OrderStatus, PaymentType  # noqa: E402
from app.routers.orders import _hide_internal  # noqa: E402
from app.schemas.order import OrderListResponse  # noqa: E402


def _actor(role: str) -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


def _order(**over) -> OrderListResponse:
    base = dict(
        id=uuid.uuid4(),
        order_number="ф42",
        order_kind=OrderKind.INDIVIDUAL,
        client_id=uuid.uuid4(),
        fuel_type="dt",
        volume_requested=500.0,
        volume_delivered=None,
        delivery_address="СПб, Невский 1",
        status=OrderStatus.NEW,
        ttn_number=None,
        pending_driver_ack=False,
        manager_id=None,
        driver_id=None,
        client_comment="позвонить за час",
        manager_comment="клиент должен 20 000 — не отгружать сверх",
        payment_type=PaymentType.PREPAID,
        payment_status="unpaid",
        expected_amount=None,
        final_amount=None,
        desired_date=None,
        created_at=datetime.now(timezone.utc),
    )
    base.update(over)
    return OrderListResponse(**base)


def test_client_does_not_see_manager_comment():
    hidden = _hide_internal(_order(), _actor("client"), OrderListResponse)
    assert hidden.manager_comment is None


def test_client_still_sees_own_comment():
    hidden = _hide_internal(_order(), _actor("client"), OrderListResponse)
    assert hidden.client_comment == "позвонить за час"


@pytest.mark.parametrize("role", ["admin", "manager", "driver"])
def test_staff_and_driver_see_manager_comment(role):
    order = _order()
    assert _hide_internal(order, _actor(role), OrderListResponse) is order


def test_list_is_filtered_element_by_element():
    orders = [_order(), _order(manager_comment=None)]
    hidden = _hide_internal(orders, _actor("client"), OrderListResponse)
    assert [o.manager_comment for o in hidden] == [None, None]


def test_source_object_is_not_mutated():
    """ORM-объект нельзя править на месте: SQLAlchemy запишет очистку в БД."""
    order = _order()
    _hide_internal(order, _actor("client"), OrderListResponse)
    assert order.manager_comment == "клиент должен 20 000 — не отгружать сверх"
