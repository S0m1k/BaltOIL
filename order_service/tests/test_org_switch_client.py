"""Смена заказчика staff-ом на любую организацию: кому достаётся заявка.

Запуск из папки order_service:  pytest tests/test_org_switch_client.py
"""
import os
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")

from app.core.exceptions import ValidationError  # noqa: E402
from app.services import order_service as svc  # noqa: E402

CLIENT, OWNER, ORG = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _target(monkeypatch, value):
    async def fake(_org_id):
        return value
    monkeypatch.setattr(svc, "get_organization_target", fake)


@pytest.mark.asyncio
async def test_client_stays_when_member_of_org(monkeypatch):
    _target(monkeypatch, {"owner_client_id": str(OWNER), "member_ids": [str(CLIENT), str(OWNER)]})
    assert await svc._client_for_org_switch(CLIENT, ORG) is None


@pytest.mark.asyncio
async def test_order_moves_to_owner_when_client_not_member(monkeypatch):
    _target(monkeypatch, {"owner_client_id": str(OWNER), "member_ids": [str(OWNER)]})
    assert await svc._client_for_org_switch(CLIENT, ORG) == OWNER


@pytest.mark.asyncio
async def test_unknown_org_is_rejected(monkeypatch):
    _target(monkeypatch, None)
    with pytest.raises(ValidationError):
        await svc._client_for_org_switch(CLIENT, ORG)


@pytest.mark.asyncio
async def test_ownerless_org_rejected_for_regular_client(monkeypatch):
    _target(monkeypatch, {"owner_client_id": None, "member_ids": []})

    async def deny(*_a, **_k):
        raise HTTPException(status_code=400, detail="no")
    monkeypatch.setattr(svc, "get_client_context", deny)
    with pytest.raises(ValidationError):
        await svc._client_for_org_switch(CLIENT, ORG)


@pytest.mark.asyncio
async def test_ownerless_org_kept_for_one_off_client(monkeypatch):
    _target(monkeypatch, {"owner_client_id": None, "member_ids": []})

    async def ok(*_a, **_k):
        return object()
    monkeypatch.setattr(svc, "get_client_context", ok)
    assert await svc._client_for_org_switch(CLIENT, ORG) is None
