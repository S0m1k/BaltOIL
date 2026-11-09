"""Поиск заявок и порядок «доставленных» (правки 2026-11-09).

Проверяем скомпилированный SQL — БД и сервисы не нужны.

Запуск из папки order_service:  pytest tests/test_order_search.py
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

from sqlalchemy.dialects import postgresql  # noqa: E402

from app.models.order import OrderStatus  # noqa: E402
from app.services import order_search  # noqa: E402


def _sql(clause) -> str:
    return str(
        clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


# ── нормализация запроса ──────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n"])
def test_blank_query_means_no_search(raw):
    assert order_search.normalize_query(raw) is None


def test_query_is_trimmed():
    assert order_search.normalize_query("  ю234 ") == "ю234"


@pytest.mark.parametrize("raw,expected", [
    ("100%", r"%100\%%"),
    ("a_b", r"%a\_b%"),
    ("c:\\x", r"%c:\\x%"),
    ("обычный", "%обычный%"),
])
def test_like_pattern_escapes_wildcards(raw, expected):
    assert order_search.like_pattern(raw) == expected


# ── условие поиска ────────────────────────────────────────────────────────────

def test_search_covers_number_ttn_address_and_contact():
    sql = _sql(order_search.build_search_condition("234", [], []))
    for column in ("order_number", "ttn_number", "delivery_address", "contact_person_name"):
        assert f"orders.{column}" in sql, column
    assert "ILIKE" in sql.upper()


def test_search_by_name_uses_buyer_ids_from_auth():
    client_id, org_id = str(uuid.uuid4()), str(uuid.uuid4())
    sql = _sql(order_search.build_search_condition("Балт", [client_id], [org_id]))
    assert "orders.client_id IN" in sql and client_id in sql
    assert "orders.organization_id IN" in sql and org_id in sql


def test_search_without_buyer_matches_does_not_add_empty_in():
    sql = _sql(order_search.build_search_condition("234", [], []))
    assert " IN " not in sql


def test_short_digit_strings_do_not_search_phone():
    sql = _sql(order_search.build_search_condition("123", [], []))
    assert "contact_person_phone" not in sql


def test_phone_is_searched_by_digits_from_four():
    sql = _sql(order_search.build_search_condition("+7 (981) 886", [], []))
    assert "contact_person_phone" in sql
    assert "regexp_replace" in sql
    assert "%7981886%" in sql


def test_injection_text_is_bound_as_literal_not_sql():
    sql = _sql(order_search.build_search_condition("x'; DROP TABLE orders;--", [], []))
    # одинарная кавычка в литерале удвоена — это данные, а не конец строки
    assert "x''; DROP TABLE orders;--" in sql


# ── порядок выдачи ────────────────────────────────────────────────────────────

def test_delivered_are_ordered_by_shipment_moment_not_by_order_number():
    order_by = order_search.order_by_clauses(OrderStatus.DELIVERED)
    first = _sql(order_by[0])
    assert "order_status_logs" in first
    # первый переход, а не последний: повторно доставленная заявка сохраняет старый ТТН
    assert "min(" in first.lower() and "max(" not in first.lower()
    assert "DESC" in first.upper()
    # номер заявки/дата создания — только запасной ключ, не главный
    assert "order_number" not in first
    assert "ttn_number" in _sql(order_by[1])


@pytest.mark.parametrize("status", [None, OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.CANCELLED])
def test_other_tabs_keep_creation_order(status):
    order_by = order_search.order_by_clauses(status)
    assert len(order_by) == 1
    assert "created_at DESC" in _sql(order_by[0])


@pytest.mark.asyncio
async def test_find_buyer_ids_degrades_when_auth_is_down(monkeypatch):
    class _Boom:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **kw): raise RuntimeError("auth недоступен")

    monkeypatch.setattr(order_search.httpx, "AsyncClient", _Boom)
    assert await order_search.find_buyer_ids("балт") == ([], [])
