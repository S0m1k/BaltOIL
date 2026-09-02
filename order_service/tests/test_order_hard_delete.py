"""Юниты полного удаления заявки (П4, 2026-09-02) — без БД и без Redis.

Сессия БД подменена фейком, который отдаёт заявку и пути документов, а затем
записывает DELETE-запросы; публикация события перехватывается монкипатчем.

Запуск из папки order_service:  pytest tests/test_order_hard_delete.py
"""
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.exceptions import ForbiddenError, NotFoundError  # noqa: E402
from app.models.order import OrderStatus  # noqa: E402
from app.services import order_service  # noqa: E402


ORDER_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ADMIN = SimpleNamespace(id=uuid.UUID("22222222-2222-2222-2222-222222222222"), role="admin")
MANAGER = SimpleNamespace(id=ADMIN.id, role="manager")


def _order(**over):
    base = dict(
        id=ORDER_ID,
        order_number="ф42",
        ttn_number="TTN-2026-000042",
        status=OrderStatus.DELIVERED,
        client_id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        driver_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        volume_delivered=593.0,
    )
    base.update(over)
    return SimpleNamespace(**base)


class _Result:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class FakeSession:
    """Минимальная замена AsyncSession: SELECT-ы по сценарию, DELETE-ы в журнал."""

    def __init__(self, order, doc_paths=()):
        self.order = order
        self.doc_paths = list(doc_paths)
        self.deleted_tables: list[str] = []
        self.commits = 0
        self._selects = 0

    async def execute(self, stmt):
        if getattr(stmt, "is_delete", False):
            self.deleted_tables.append(stmt.table.name)
            return _Result()
        self._selects += 1
        if self._selects == 1:           # SELECT Order
            return _Result(scalar=self.order)
        return _Result(rows=self.doc_paths)  # SELECT Document.file_path

    async def commit(self):
        self.commits += 1


@pytest.fixture
def captured(monkeypatch):
    """Перехват публикации события и удаления файлов с диска."""
    events: list[dict] = []
    removed: list[list[str]] = []

    async def _publish(payload):
        events.append(payload)

    monkeypatch.setattr(order_service, "publish_order_event", _publish)
    monkeypatch.setattr(order_service, "_remove_document_files", lambda paths: removed.append(paths))
    return SimpleNamespace(events=events, removed=removed)


# ── Доступ ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["manager", "driver", "client"])
async def test_hard_delete_forbidden_for_non_admin(role, captured):
    db = FakeSession(_order())
    actor = SimpleNamespace(id=MANAGER.id, role=role)

    with pytest.raises(ForbiddenError):
        await order_service.hard_delete_order(db, ORDER_ID, actor)

    # Ничего не удалено и событие не отправлено
    assert db.deleted_tables == []
    assert db.commits == 0
    assert captured.events == []


@pytest.mark.asyncio
async def test_hard_delete_missing_order(captured):
    db = FakeSession(order=None)
    with pytest.raises(NotFoundError):
        await order_service.hard_delete_order(db, ORDER_ID, ADMIN)
    assert captured.events == []


# ── Каскад ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_delete_cascade_and_files(captured):
    db = FakeSession(_order(), doc_paths=["documents/1/INV.pdf", "documents/1/TTN.pdf"])

    res = await order_service.hard_delete_order(db, ORDER_ID, ADMIN)

    assert db.deleted_tables == [
        "documents", "payments", "order_status_logs", "idempotency_keys", "orders",
    ]
    assert db.commits == 1
    assert captured.removed == [["documents/1/INV.pdf", "documents/1/TTN.pdf"]]
    assert res == {"deleted": True, "order_number": "ф42", "stock_restored_l": 593.0}


@pytest.mark.asyncio
async def test_hard_delete_undelivered_order_restores_nothing(captured):
    db = FakeSession(_order(status=OrderStatus.NEW, volume_delivered=None))
    res = await order_service.hard_delete_order(db, ORDER_ID, ADMIN)
    assert res["stock_restored_l"] is None


# ── Событие ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hard_delete_publishes_order_deleted_event(captured):
    db = FakeSession(_order())

    await order_service.hard_delete_order(db, ORDER_ID, ADMIN)

    assert len(captured.events) == 1
    ev = captured.events[0]
    assert ev["event"] == "order_deleted"
    assert ev["order_id"] == str(ORDER_ID)
    assert ev["order_number"] == "ф42"
    assert ev["ttn_number"] == "TTN-2026-000042"
    assert ev["actor_id"] == str(ADMIN.id)
