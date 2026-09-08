"""Права на справочники перевозки (ТЗ: ведут админ и менеджер).

Проверки прав — первое, что делает сервис, до любого обращения к БД, поэтому
сессию подсовывать не нужно: до неё выполнение не доходит.

Запуск из папки order_service:  pytest tests/test_transport_directory_permissions.py
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
from app.core.exceptions import ForbiddenError  # noqa: E402
from app.schemas.transport import (  # noqa: E402
    TransportBaseCreateRequest, TransportClientObjectCreateRequest,
)
from app.services import transport_directory  # noqa: E402


def _actor(role: str) -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, token="t")


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_staff_passes_write_guard(role):
    transport_directory._require_staff(_actor(role))


@pytest.mark.parametrize("role", ["driver", "client"])
def test_non_staff_cannot_write_directory(role):
    with pytest.raises(ForbiddenError):
        transport_directory._require_staff(_actor(role))


@pytest.mark.parametrize("role", ["manager", "admin", "driver"])
def test_driver_and_staff_may_read_directory(role):
    # Водителю названия точек маршрута нужны для карточки перевозки
    transport_directory._require_reader(_actor(role))


def test_client_never_reads_transport_directory():
    with pytest.raises(ForbiddenError):
        transport_directory._require_reader(_actor("client"))


@pytest.mark.asyncio
async def test_create_base_rejects_client_before_touching_db():
    data = TransportBaseCreateRequest(name="Нефтебаза №1", default_delivery_cost=5000)
    with pytest.raises(ForbiddenError):
        await transport_directory.create_base(None, data, _actor("client"))


@pytest.mark.asyncio
async def test_create_client_object_rejects_driver_before_touching_db():
    data = TransportClientObjectCreateRequest(name="ООО Ромашка", addresses=["СПб"])
    with pytest.raises(ForbiddenError):
        await transport_directory.create_client_object(None, data, _actor("driver"))


# ── Нормализация адресов объекта ──────────────────────────────────────────────

def test_clean_addresses_trims_drops_empty_and_dedupes_keeping_order():
    result = transport_directory._clean_addresses(
        ["  СПб, Невский 1 ", "", "Москва", "СПб, Невский 1", "   ", "Тверь"]
    )
    assert result == ["СПб, Невский 1", "Москва", "Тверь"]
