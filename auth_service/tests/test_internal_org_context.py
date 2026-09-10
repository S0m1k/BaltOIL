"""Контекст организации для разового клиента (баг 2026-09-10).

Разовый клиент (имя+телефон из формы заявки) не состоит ни в одной организации
и войти в систему не может — заявку от юрлица на него оформляет сотрудник.
Проверка членства рубила такую заявку: order_service получал 404 и считал
заявку по тарифам физлица. Теперь для разового клиента членство не требуется.

Требуется живой PostgreSQL — см. tests/conftest.py.
    cd auth_service && python -m pytest tests/test_internal_org_context.py
"""
import pytest
from fastapi import HTTPException

from app.core.security import hash_password
from app.models.client_profile import ClientProfile, ClientType
from app.models.organization import Organization
from app.models.user import User, UserRole
from app.routers.internal import _load_member_org


async def _make_client(db, *, is_one_off: bool, phone: str) -> User:
    user = User(
        email=None,
        phone=phone,
        hashed_password=hash_password("Password123"),
        full_name="Иван Разовый" if is_one_off else "Иван Обычный",
        role=UserRole.CLIENT,
    )
    db.add(user)
    await db.flush()
    db.add(ClientProfile(
        user_id=user.id,
        client_type=ClientType.INDIVIDUAL,
        is_one_off=is_one_off,
    ))
    await db.flush()
    return user


async def _make_org(db, *, tariff_id=None) -> Organization:
    org = Organization(company_name="ООО «Тест»", inn="7712345678", credit_allowed=True)
    if tariff_id is not None:
        org.tariff_id = tariff_id
    db.add(org)
    await db.flush()
    return org


async def test_one_off_client_gets_org_context_without_membership(db):
    """Разовый клиент + организация → контекст организации (тариф юрлица)."""
    user = await _make_client(db, is_one_off=True, phone="+79990000101")
    org = await _make_org(db)

    loaded = await _load_member_org(db, user.id, org.id)

    assert loaded.id == org.id


async def test_regular_client_without_membership_still_rejected(db):
    """Обычный клиент чужой организации по-прежнему получает 404."""
    user = await _make_client(db, is_one_off=False, phone="+79990000102")
    org = await _make_org(db)

    with pytest.raises(HTTPException) as exc:
        await _load_member_org(db, user.id, org.id)

    assert exc.value.status_code == 404


async def test_one_off_client_archived_org_rejected(db):
    """Архивная организация не выдаётся даже разовому клиенту."""
    user = await _make_client(db, is_one_off=True, phone="+79990000103")
    org = await _make_org(db)
    org.is_archived = True
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await _load_member_org(db, user.id, org.id)

    assert exc.value.status_code == 404
