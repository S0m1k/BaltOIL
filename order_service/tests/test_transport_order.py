"""Заявка на перевозку: права, видимость, ТТН, маршрут, блок 2 (ТЗ 09.2026).

Все проверки — без БД и без сети: либо чистые функции, либо гарды, которые
срабатывают раньше первого обращения к сессии.

Запуск из папки order_service:  pytest tests/test_transport_order.py
"""
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.dependencies import TokenUser  # noqa: E402
from app.core.exceptions import ForbiddenError, ValidationError  # noqa: E402
from app.models.order import OrderKind  # noqa: E402
from app.models.transport import RoutePointKind, TransportDetail, TransportType  # noqa: E402
from app.schemas.transport import (  # noqa: E402
    RoutePoint, TransportOrderCreateRequest,
)
from app.services import transport_service  # noqa: E402
from app.services.buyer_info import TRANSPORT_BUYER_LABEL, attach_buyer_names  # noqa: E402
from app.services.order_number import _KIND_PREFIX  # noqa: E402
from app.services.order_service import _visibility_conditions  # noqa: E402
from app.services.ttn_number import TtnKind, resolve_ttn_kind  # noqa: E402


def _actor(role: str) -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


def _sql(conditions) -> str:
    return " ".join(
        str(c.compile(compile_kwargs={"literal_binds": True})) for c in conditions
    )


# ── ТТН: перевозка идёт в общем ряду с юрлицами (Ю), а НЕ в Л ─────────────────

def test_transport_ttn_goes_to_company_row():
    assert resolve_ttn_kind(OrderKind.TRANSPORT) is TtnKind.COMPANY


def test_transport_ttn_is_not_special_l_row():
    assert resolve_ttn_kind(OrderKind.TRANSPORT) is not TtnKind.SPECIAL


def test_ttn_l_still_uses_its_own_row():
    # Регресс: добавление перевозки не должно сдвинуть ТТН-Л с ряда Л
    assert resolve_ttn_kind(OrderKind.TTN_L) is TtnKind.SPECIAL


def test_transport_order_number_has_own_prefix():
    assert _KIND_PREFIX[OrderKind.TRANSPORT.value] == "п"


# ── Видимость: клиент — никогда, водитель — только назначенные ────────────────

def test_client_never_sees_transport_orders():
    sql = _sql(_visibility_conditions(_actor("client")))
    assert "order_kind != " in sql.replace("!=", "!= ").replace("  ", " ") or \
           "TRANSPORT" in sql.upper()


def test_client_visibility_excludes_transport_kind():
    sql = _sql(_visibility_conditions(_actor("client"))).upper()
    assert "TRANSPORT" in sql


def test_driver_pool_excludes_transport_and_ttn_l():
    sql = _sql(_visibility_conditions(_actor("driver"))).upper()
    # Свободные NEW из «биржи» не должны включать перевозки и ТТН-Л
    assert "TRANSPORT" in sql
    assert "TTN_L" in sql
    assert "DRIVER_ID" in sql


def test_staff_visibility_unchanged_by_transport():
    for role in ("manager", "admin"):
        sql = _sql(_visibility_conditions(_actor(role))).upper()
        assert "TRANSPORT" not in sql  # staff видит всё, фильтра нет


# ── Права на создание и правку ───────────────────────────────────────────────

def _create_payload() -> TransportOrderCreateRequest:
    return TransportOrderCreateRequest(
        transport_type=TransportType.TO_BASE,
        route_from=RoutePoint(kind=RoutePointKind.OIL_DEPOT, id=uuid.uuid4()),
        route_to=RoutePoint(kind=RoutePointKind.BASE, text="База"),
        amount_kg=Decimal("1000"),
    )


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_staff_passes_transport_write_guard(role):
    transport_service._require_staff(_actor(role))


@pytest.mark.parametrize("role", ["driver", "client"])
def test_non_staff_cannot_write_transport(role):
    with pytest.raises(ForbiddenError):
        transport_service._require_staff(_actor(role))


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["driver", "client"])
async def test_create_transport_rejects_non_staff_before_db(role):
    with pytest.raises(ForbiddenError):
        await transport_service.create_transport_order(None, _create_payload(), _actor(role))


# ── Маршрут ──────────────────────────────────────────────────────────────────

def test_route_point_serializes_kind_id_and_text():
    pid = uuid.uuid4()
    out = transport_service._point_to_dict(
        RoutePoint(kind=RoutePointKind.CLIENT_OBJECT, id=pid, text="  Склад  ")
    )
    assert out == {"kind": "client_object", "id": str(pid), "text": "Склад"}


def test_route_point_blank_text_becomes_none():
    out = transport_service._point_to_dict(RoutePoint(kind=RoutePointKind.BASE, text="   "))
    assert out["text"] is None


def test_route_point_none_stays_none():
    assert transport_service._point_to_dict(None) is None


def test_waypoints_limited_to_three():
    points = [RoutePoint(kind=RoutePointKind.CLIENT_OBJECT, text=f"т{i}") for i in range(4)]
    with pytest.raises(ValidationError):
        transport_service._normalize_waypoints(points)


def test_three_waypoints_are_accepted():
    points = [RoutePoint(kind=RoutePointKind.CLIENT_OBJECT, text=f"т{i}") for i in range(3)]
    assert len(transport_service._normalize_waypoints(points)) == 3


# ── Оплаты поставщику ────────────────────────────────────────────────────────

def test_supplier_payments_drop_fully_empty_rows():
    rows = transport_service._normalize_supplier_payments(
        [{"amount": "100", "date": "2026-09-01"}, {"amount": None, "date": None}]
    )
    assert rows == [{"amount": "100", "date": "2026-09-01"}]


def test_supplier_payments_limited_to_four():
    rows = [{"amount": "1", "date": None} for _ in range(5)]
    with pytest.raises(ValidationError):
        transport_service._normalize_supplier_payments(rows)


def test_supplier_payment_rejects_negative_amount():
    with pytest.raises(ValidationError):
        transport_service._normalize_supplier_payments([{"amount": "-5", "date": None}])


def test_supplier_payment_rejects_garbage_amount():
    with pytest.raises(ValidationError):
        transport_service._normalize_supplier_payments([{"amount": "полтинник", "date": None}])


# ── Блок 2 виден только staff ────────────────────────────────────────────────

def _detail() -> TransportDetail:
    return TransportDetail(
        order_id=uuid.uuid4(),
        transport_type=TransportType.TO_BASE.value,
        amount_kg=Decimal("1000"),
        amount_l=Decimal("840"),
        density=Decimal("0.84"),
        price_per_kg=Decimal("50"),
        total_amount=Decimal("50000"),
        supplier_payments=[{"amount": "20000", "date": "2026-09-01"}],
        delivery_price=Decimal("7000"),
        delivery_paid=True,
        driver_payment_amount=Decimal("12500"),
        driver_payment_percent=Decimal("25"),
    )


class _FakeOrder:
    def __init__(self, detail):
        self.transport = detail


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["manager", "admin"])
async def test_staff_sees_block2_of_transport(role):
    payload = await transport_service.detail_response(
        None, _FakeOrder(_detail()), _actor(role)
    )
    for field in transport_service.BLOCK2_FIELDS:
        assert field in payload
    assert payload["supplier_paid_total"] == Decimal("20000.00")


@pytest.mark.asyncio
async def test_driver_sees_only_block1_of_transport():
    payload = await transport_service.detail_response(
        None, _FakeOrder(_detail()), _actor("driver")
    )
    for field in transport_service.BLOCK2_FIELDS:
        assert field not in payload
    # Блок 1 водителю нужен целиком
    for field in transport_service.BLOCK1_FIELDS:
        assert field in payload


@pytest.mark.asyncio
async def test_transport_without_detail_returns_none():
    assert await transport_service.detail_response(
        None, _FakeOrder(None), _actor("admin")
    ) is None


# ── Блок 2: формулы применяются при записи ───────────────────────────────────

def test_write_block2_fills_liters_total_and_driver_share():
    detail = TransportDetail(order_id=uuid.uuid4(), transport_type="to_base")
    detail.amount_kg = Decimal("1000")
    data = TransportOrderCreateRequest(
        transport_type=TransportType.TO_BASE,
        amount_kg=Decimal("1000"),
        density=Decimal("0.84"),
        price_per_kg=Decimal("50"),
    )
    transport_service._write_block2(detail, data, is_create=True)
    assert detail.amount_l == Decimal("840.000")
    assert detail.total_amount == Decimal("50000.00")
    assert detail.driver_payment_amount == Decimal("12500.00")  # 25 % по умолчанию


def test_write_block2_keeps_manual_driver_amount():
    detail = TransportDetail(order_id=uuid.uuid4(), transport_type="to_base")
    detail.amount_kg = Decimal("1000")
    data = TransportOrderCreateRequest(
        transport_type=TransportType.TO_BASE,
        amount_kg=Decimal("1000"),
        price_per_kg=Decimal("50"),
        driver_payment_amount=Decimal("9000"),
    )
    transport_service._write_block2(detail, data, is_create=True)
    assert detail.driver_payment_amount == Decimal("9000")


# ── «ПЕРЕВОЗКА» вместо названия организации ──────────────────────────────────

class _ListedOrder:
    def __init__(self, kind):
        self.order_kind = kind
        self.client_id = uuid.uuid4()
        self.organization_id = None
        self.buyer_name = None


@pytest.mark.asyncio
async def test_transport_is_labelled_and_never_queries_auth(monkeypatch):
    async def _explode(_items):
        raise AssertionError("для перевозки в auth ходить не нужно")

    monkeypatch.setattr("app.services.buyer_info._fetch_names", _explode)
    orders = [_ListedOrder(OrderKind.TRANSPORT)]
    await attach_buyer_names(orders)
    assert orders[0].buyer_name == TRANSPORT_BUYER_LABEL == "ПЕРЕВОЗКА"


@pytest.mark.asyncio
async def test_regular_orders_still_resolve_buyer_names(monkeypatch):
    captured = {}

    async def _fake(items):
        captured["items"] = items
        return {f"{items[0]['client_id']}|": "ООО Ромашка"}

    monkeypatch.setattr("app.services.buyer_info._fetch_names", _fake)
    transport = _ListedOrder(OrderKind.TRANSPORT)
    company = _ListedOrder(OrderKind.COMPANY)
    await attach_buyer_names([transport, company])
    assert company.buyer_name == "ООО Ромашка"
    assert transport.buyer_name == "ПЕРЕВОЗКА"
    # Перевозка не попадает в батч-запрос имён
    assert len(captured["items"]) == 1
