"""CRM-45: адрес и контакт приёмки запоминаются на клиенте и организации.

Сессию подменяем фейком: проверяем логику upsert, а не SQL.

Запуск из папки order_service:  pytest tests/test_client_object_memory.py
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
from app.models.client_object import ClientObject  # noqa: E402
from app.services import client_object_service  # noqa: E402

CLIENT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
ACTOR = TokenUser(id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
                  role="manager", token="t")


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _NestedTx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Отдаёт заранее заданный объект на первый SELECT и счётчик — на второй."""

    def __init__(self, existing: ClientObject | None = None, count: int = 0):
        self._existing = existing
        self._count = count
        self._calls = 0
        self.added: list = []
        self.flushed = 0

    async def execute(self, _stmt):
        self._calls += 1
        return _Result(self._existing if self._calls == 1 else self._count)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed += 1

    def begin_nested(self):
        return _NestedTx()


def _order(**over):
    base = dict(
        client_id=CLIENT_ID,
        organization_id=ORG_ID,
        delivery_address="СПб, Невский 1",
        delivery_lat=None,
        delivery_lon=None,
        contact_person_name="Пётр Петров",
        contact_person_phone="+79990000000",
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_new_address_is_saved_with_contact_and_organization():
    db = FakeSession()
    await client_object_service.remember_from_order(db, _order(), ACTOR)

    assert len(db.added) == 1
    obj = db.added[0]
    assert obj.client_id == CLIENT_ID
    assert obj.organization_id == ORG_ID
    assert obj.delivery_address == "СПб, Невский 1"
    assert obj.contact_person_name == "Пётр Петров"
    assert obj.contact_person_phone == "+79990000000"


@pytest.mark.asyncio
async def test_known_address_is_updated_not_duplicated():
    existing = ClientObject(client_id=CLIENT_ID, delivery_address="СПб, Невский 1")
    db = FakeSession(existing=existing)

    await client_object_service.remember_from_order(db, _order(), ACTOR)

    assert db.added == []  # дубликата не появилось
    assert existing.contact_person_name == "Пётр Петров"
    assert existing.organization_id == ORG_ID


@pytest.mark.asyncio
async def test_empty_contact_does_not_erase_known_one():
    existing = ClientObject(
        client_id=CLIENT_ID, delivery_address="СПб, Невский 1",
        contact_person_name="Пётр Петров", contact_person_phone="+79990000000",
    )
    db = FakeSession(existing=existing)

    await client_object_service.remember_from_order(
        db, _order(contact_person_name=None, contact_person_phone=None), ACTOR)

    assert existing.contact_person_name == "Пётр Петров"
    assert existing.contact_person_phone == "+79990000000"


@pytest.mark.asyncio
@pytest.mark.parametrize("address", [None, "", "   "])
async def test_empty_address_is_not_saved(address):
    # CRM-37: заявка со слов может быть без адреса — сохранять нечего
    db = FakeSession()
    await client_object_service.remember_from_order(db, _order(delivery_address=address), ACTOR)
    assert db.added == []


@pytest.mark.asyncio
async def test_address_is_trimmed_before_lookup():
    db = FakeSession()
    await client_object_service.remember_from_order(
        db, _order(delivery_address="  СПб, Невский 1  "), ACTOR)
    assert db.added[0].delivery_address == "СПб, Невский 1"


@pytest.mark.asyncio
async def test_cap_stops_new_objects_but_never_breaks_the_order():
    db = FakeSession(count=client_object_service._CAP)
    await client_object_service.remember_from_order(db, _order(), ACTOR)
    assert db.added == []


@pytest.mark.asyncio
async def test_db_failure_is_swallowed():
    # Справочник адресов не стоит того, чтобы из-за него падало создание заявки
    class Boom(FakeSession):
        async def execute(self, _stmt):
            raise RuntimeError("db is down")

    await client_object_service.remember_from_order(Boom(), _order(), ACTOR)
