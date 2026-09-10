"""Предикат исключений из проверки членства — без БД.

Файл test_internal_org_context.py проверяет тот же контракт на живом
PostgreSQL, но БД есть не везде (CI, машина разработчика без Docker), а
регрессия здесь дорогая: ослабишь предикат — и контекст любой организации
начнёт выдаваться постороннему клиенту; ужесточишь — вернётся баг
2026-09-10 «разовая заявка от юрлица считается по тарифам физлица».
Поэтому логика ветвления закреплена на стабе сессии и гоняется всегда.
"""
import uuid

import pytest

from app.models.user import UserRole
from app.routers.internal import _membership_not_required


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeUser:
    def __init__(self, role):
        self.role = role


class _FakeSession:
    """Отдаёт заранее заданного пользователя и флаг is_one_off."""

    def __init__(self, *, user=None, is_one_off=None):
        self._user = user
        self._is_one_off = is_one_off
        self.execute_calls = 0

    async def get(self, _model, _pk):
        return self._user

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _ScalarResult(self._is_one_off)


@pytest.mark.asyncio
async def test_manager_skips_membership_check():
    db = _FakeSession(user=_FakeUser(UserRole.MANAGER))
    assert await _membership_not_required(db, uuid.uuid4()) is True
    # Профиль не запрашиваем: роль уже всё решила.
    assert db.execute_calls == 0


@pytest.mark.asyncio
async def test_admin_skips_membership_check():
    db = _FakeSession(user=_FakeUser(UserRole.ADMIN))
    assert await _membership_not_required(db, uuid.uuid4()) is True


@pytest.mark.asyncio
async def test_one_off_client_skips_membership_check():
    """Разовый клиент — тот самый баг: без исключения тариф уходил в физлицо."""
    db = _FakeSession(user=_FakeUser(UserRole.CLIENT), is_one_off=True)
    assert await _membership_not_required(db, uuid.uuid4()) is True


@pytest.mark.asyncio
async def test_regular_client_still_requires_membership():
    """Обычный клиент не должен получать контекст чужой организации."""
    db = _FakeSession(user=_FakeUser(UserRole.CLIENT), is_one_off=False)
    assert await _membership_not_required(db, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_client_without_profile_requires_membership():
    """Профиля нет — считаем обычным клиентом, а не разовым."""
    db = _FakeSession(user=_FakeUser(UserRole.CLIENT), is_one_off=None)
    assert await _membership_not_required(db, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_driver_requires_membership():
    db = _FakeSession(user=_FakeUser(UserRole.DRIVER), is_one_off=False)
    assert await _membership_not_required(db, uuid.uuid4()) is False


@pytest.mark.asyncio
async def test_unknown_user_requires_membership():
    """Пользователя нет — никаких исключений."""
    db = _FakeSession(user=None)
    assert await _membership_not_required(db, uuid.uuid4()) is False
