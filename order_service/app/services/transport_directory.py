"""Справочники перевозки: нефтебазы и объекты клиентов.

Читать справочники может любой сотрудник (менеджер, админ) и водитель
перевозок — ему нужны названия точек маршрута в карточке заявки. Заводить и
править — только админ и менеджер (ТЗ: «добавляет админ/менеджер»).
Клиенту справочники перевозки не видны вовсе, как и сами перевозки.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenUser
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.transport import (
    TransportBase, TransportClientAddress, TransportClientObject,
)
from app.schemas.transport import (
    TransportBaseCreateRequest, TransportBaseUpdateRequest,
    TransportClientObjectCreateRequest, TransportClientObjectUpdateRequest,
)

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_DRIVER = "driver"

STAFF_ROLES = (ROLE_MANAGER, ROLE_ADMIN)
#: Кто вообще может увидеть справочники перевозки (клиента здесь нет).
READER_ROLES = (ROLE_MANAGER, ROLE_ADMIN, ROLE_DRIVER)


def _require_reader(actor: TokenUser) -> None:
    if actor.role not in READER_ROLES:
        raise ForbiddenError("Справочники перевозки недоступны")


def _require_staff(actor: TokenUser) -> None:
    if actor.role not in STAFF_ROLES:
        raise ForbiddenError("Справочники перевозки ведут менеджер и администратор")


# ── Нефтебазы ─────────────────────────────────────────────────────────────────


async def list_bases(
    db: AsyncSession, actor: TokenUser, *, include_inactive: bool = False
) -> list[TransportBase]:
    _require_reader(actor)
    query = select(TransportBase).order_by(TransportBase.name)
    if not include_inactive:
        query = query.where(TransportBase.is_active == True)  # noqa: E712
    return list((await db.execute(query)).scalars().all())


async def create_base(
    db: AsyncSession, data: TransportBaseCreateRequest, actor: TokenUser
) -> TransportBase:
    _require_staff(actor)
    name = data.name.strip()
    if not name:
        raise ValidationError("Укажите название нефтебазы")
    base = TransportBase(
        name=name,
        default_delivery_cost=data.default_delivery_cost,
        created_by_id=actor.id,
    )
    db.add(base)
    await db.flush()
    return base


async def update_base(
    db: AsyncSession, base_id: uuid.UUID, data: TransportBaseUpdateRequest, actor: TokenUser
) -> TransportBase:
    _require_staff(actor)
    base = (
        await db.execute(select(TransportBase).where(TransportBase.id == base_id))
    ).scalar_one_or_none()
    if base is None:
        raise NotFoundError("Нефтебаза не найдена")

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise ValidationError("Укажите название нефтебазы")
        base.name = name
    if "default_delivery_cost" in data.model_fields_set:
        base.default_delivery_cost = data.default_delivery_cost
    if data.is_active is not None:
        base.is_active = data.is_active
    await db.flush()
    return base


async def delete_base(db: AsyncSession, base_id: uuid.UUID, actor: TokenUser) -> None:
    """Мягкое удаление: маршруты уже созданных заявок ссылаются на нефтебазу."""
    _require_staff(actor)
    base = (
        await db.execute(select(TransportBase).where(TransportBase.id == base_id))
    ).scalar_one_or_none()
    if base is None:
        raise NotFoundError("Нефтебаза не найдена")
    base.is_active = False
    await db.flush()


# ── Объекты клиентов ──────────────────────────────────────────────────────────


async def list_client_objects(
    db: AsyncSession, actor: TokenUser, *, include_inactive: bool = False
) -> list[TransportClientObject]:
    _require_reader(actor)
    query = select(TransportClientObject).order_by(TransportClientObject.name)
    if not include_inactive:
        query = query.where(TransportClientObject.is_active == True)  # noqa: E712
    return list((await db.execute(query)).scalars().all())


async def get_client_object(
    db: AsyncSession, object_id: uuid.UUID, actor: TokenUser
) -> TransportClientObject:
    _require_reader(actor)
    obj = (
        await db.execute(
            select(TransportClientObject).where(TransportClientObject.id == object_id)
        )
    ).scalar_one_or_none()
    if obj is None:
        raise NotFoundError("Объект клиента не найден")
    return obj


def _clean_addresses(raw: list[str]) -> list[str]:
    """Обрезать, выбросить пустые и дубли, сохранив порядок ввода."""
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        address = (item or "").strip()
        if not address or address in seen:
            continue
        seen.add(address)
        out.append(address)
    return out


async def create_client_object(
    db: AsyncSession, data: TransportClientObjectCreateRequest, actor: TokenUser
) -> TransportClientObject:
    _require_staff(actor)
    name = data.name.strip()
    if not name:
        raise ValidationError("Укажите название объекта")
    obj = TransportClientObject(
        name=name,
        client_id=data.client_id,
        created_by_id=actor.id,
    )
    for i, address in enumerate(_clean_addresses(data.addresses)):
        obj.addresses.append(TransportClientAddress(address=address, sort_order=i))
    db.add(obj)
    await db.flush()
    return obj


async def update_client_object(
    db: AsyncSession,
    object_id: uuid.UUID,
    data: TransportClientObjectUpdateRequest,
    actor: TokenUser,
) -> TransportClientObject:
    _require_staff(actor)
    obj = await get_client_object(db, object_id, actor)

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise ValidationError("Укажите название объекта")
        obj.name = name
    # client_id=null — валидное «открепить клиента», поэтому смотрим fields_set.
    if "client_id" in data.model_fields_set:
        obj.client_id = data.client_id
    if data.is_active is not None:
        obj.is_active = data.is_active
    if data.addresses is not None:
        obj.addresses.clear()
        for i, address in enumerate(_clean_addresses(data.addresses)):
            obj.addresses.append(TransportClientAddress(address=address, sort_order=i))
    await db.flush()
    return obj


async def delete_client_object(
    db: AsyncSession, object_id: uuid.UUID, actor: TokenUser
) -> None:
    """Мягкое удаление — маршруты созданных заявок ссылаются на объект."""
    _require_staff(actor)
    obj = await get_client_object(db, object_id, actor)
    obj.is_active = False
    await db.flush()


async def set_contract_file(
    db: AsyncSession,
    object_id: uuid.UUID,
    file_path: str,
    file_name: str,
    actor: TokenUser,
) -> TransportClientObject:
    _require_staff(actor)
    obj = await get_client_object(db, object_id, actor)
    obj.contract_file_path = file_path
    obj.contract_file_name = file_name
    await db.flush()
    return obj


def to_response_dict(obj: TransportClientObject) -> dict:
    """Объект клиента в словарь ответа: путь к файлу наружу не отдаём."""
    return {
        "id": obj.id,
        "name": obj.name,
        "client_id": obj.client_id,
        "contract_file_name": obj.contract_file_name,
        "has_contract": bool(obj.contract_file_path),
        "is_active": obj.is_active,
        "addresses": [
            {"id": a.id, "address": a.address, "sort_order": a.sort_order}
            for a in obj.addresses
        ],
        "created_at": obj.created_at,
    }
