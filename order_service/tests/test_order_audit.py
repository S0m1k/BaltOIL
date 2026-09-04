"""CRM-44: журнал действий по заявке.

Проверяем чистые части — приведение значений, русские формулировки и диф полей.
БД не нужна: `record` только кладёт объект в сессию, поэтому сессию подменяем
списком.

Запуск из папки order_service:  pytest tests/test_order_audit.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.dependencies import TokenUser  # noqa: E402
from app.models.order import OrderStatus, PaymentType  # noqa: E402
from app.services import order_audit  # noqa: E402
from app.services.order_service import _audit_diff, _audit_snapshot  # noqa: E402

ORDER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")


class FakeSession:
    """Минимальная замена AsyncSession: журналу нужен только `add`."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def _actor(role: str = "admin") -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


def _order(**over):
    base = dict(
        id=ORDER_ID,
        fuel_type="diesel_summer",
        volume_requested=3000,
        volume_delivered=None,
        delivery_address="СПб, Невский 1",
        desired_date=None,
        contact_person_name=None,
        contact_person_phone=None,
        client_comment=None,
        manager_comment=None,
        driver_id=None,
        expected_amount=Decimal("100000.00"),
        final_amount=None,
        delivery_cost=Decimal("5000"),
        payment_type=PaymentType.ON_DELIVERY,
        organization_id=None,
        allow_delivery_unpaid=False,
        trade_credit_contract_signed=False,
    )
    base.update(over)
    return SimpleNamespace(**base)


# ── stringify ────────────────────────────────────────────────────────────────

def test_stringify_enum_uses_value_not_python_repr():
    # str(PaymentType.DEBT) в 3.12 даёт «PaymentType.DEBT» — в журнале это мусор
    assert order_audit.stringify(PaymentType.DEBT) == "debt"
    assert order_audit.stringify(OrderStatus.DELIVERED) == "delivered"


def test_stringify_numbers_drop_trailing_zeros():
    assert order_audit.stringify(Decimal("3000.00")) == "3000"
    assert order_audit.stringify(Decimal("3000.50")) == "3000.50"


def test_stringify_empty_and_none_collapse_to_none():
    assert order_audit.stringify(None) is None
    assert order_audit.stringify("   ") is None


def test_stringify_date_is_calendar_day():
    dt = datetime(2026, 9, 4, 23, 30, tzinfo=timezone.utc)
    assert order_audit.stringify(dt) == "2026-09-04"


# ── формулировки ─────────────────────────────────────────────────────────────

def _entry(**over):
    base = dict(actor_role="admin", action=order_audit.ACTION_FIELD, field=None,
                old_value=None, new_value=None)
    base.update(over)
    return SimpleNamespace(**base)


def test_describe_created():
    assert order_audit.describe(_entry(action=order_audit.ACTION_CREATED), "Ирина") \
        == "Ирина создал(а) заявку"


def test_describe_volume_change_has_units():
    msg = order_audit.describe(
        _entry(field="volume_requested", old_value="3000", new_value="2800"), "Сомов",
    )
    assert msg == "Сомов изменил(а) объём 3000 л → 2800 л"


def test_describe_payment_recorded():
    msg = order_audit.describe(
        _entry(action=order_audit.ACTION_PAYMENT, field="cash", new_value="15000"),
        "Сомов",
    )
    assert "отметил(а) оплату получена" in msg
    assert "15000 ₽" in msg


def test_describe_status_delivered_reads_as_action():
    msg = order_audit.describe(
        _entry(action=order_audit.ACTION_STATUS, old_value="accepted",
               new_value="delivered"), "Волков",
    )
    assert msg == "Волков отметил(а) заявку доставленной"


def test_describe_falls_back_to_role_when_name_unknown():
    # auth_service недоступен → вместо ФИО показываем роль, а не пустоту
    msg = order_audit.describe(_entry(action=order_audit.ACTION_CREATED), None)
    assert msg.startswith("Администратор")


def test_describe_added_and_cleared_fields():
    added = order_audit.describe(
        _entry(field="contact_person_name", new_value="Пётр"), "Ирина")
    assert added == "Ирина добавил(а) контактное лицо: Пётр"
    cleared = order_audit.describe(
        _entry(field="contact_person_name", old_value="Пётр"), "Ирина")
    assert "очистил(а) контактное лицо" in cleared


def test_describe_payment_type_value_is_russian():
    msg = order_audit.describe(
        _entry(field="payment_type", old_value="prepaid", new_value="debt"), "Ирина")
    assert "предоплата → в долг" in msg


# ── диф полей ────────────────────────────────────────────────────────────────

def test_audit_diff_records_only_changed_fields():
    order = _order()
    before = _audit_snapshot(order)
    order.volume_requested = 2800
    order.contact_person_phone = "+79990000000"

    db = FakeSession()
    _audit_diff(db, order, _actor(), before)

    changed = {(e.field, e.old_value, e.new_value) for e in db.added}
    assert changed == {
        ("volume_requested", "3000", "2800"),
        ("contact_person_phone", None, "+79990000000"),
    }
    assert all(e.order_id == ORDER_ID for e in db.added)
    assert all(e.action == order_audit.ACTION_FIELD for e in db.added)


def test_audit_diff_is_silent_without_changes():
    order = _order()
    db = FakeSession()
    _audit_diff(db, order, _actor(), _audit_snapshot(order))
    assert db.added == []


def test_audit_diff_catches_indirect_amount_recalc():
    # Правка объёма пересчитывает сумму — в журнале должны быть обе строки
    order = _order()
    before = _audit_snapshot(order)
    order.volume_requested = 2800
    order.expected_amount = Decimal("95000.00")

    db = FakeSession()
    _audit_diff(db, order, _actor(), before)
    assert {e.field for e in db.added} == {"volume_requested", "expected_amount"}


def test_record_keeps_actor_role_and_id():
    db = FakeSession()
    actor = _actor("manager")
    order_audit.record(db, ORDER_ID, actor, order_audit.ACTION_CREATED)
    entry = db.added[0]
    assert entry.actor_id == actor.id
    assert entry.actor_role == "manager"


@pytest.mark.parametrize("field", [
    "fuel_type", "volume_requested", "delivery_address", "desired_date",
    "contact_person_name", "contact_person_phone", "client_comment",
    "manager_comment", "expected_amount", "final_amount", "delivery_cost",
])
def test_every_audited_field_has_russian_label(field):
    assert field in order_audit.FIELD_LABELS
