"""Tariff CRUD service.

Access rules (enforced here, not in the router):
- Listing / reading tariffs:  manager, admin
- Editing default tariff prices+tiers: manager, admin
- Creating / archiving / set-default / editing non-default: admin only
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tariff import Tariff, TariffFuelPrice, TariffVolumeTier
from app.models.order import FuelType
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.core.dependencies import TokenUser

_ADMIN = "admin"
_MANAGER = "manager"
_STAFF = {_ADMIN, _MANAGER}

# All valid fuel_type values as stored in tariff_fuel_prices
_VALID_FUEL_TYPES = {ft.value.upper() for ft in FuelType}


def _check_admin(actor: TokenUser) -> None:
    if actor.role != _ADMIN:
        raise ForbiddenError("Только администратор может выполнять это действие")


def _check_staff(actor: TokenUser) -> None:
    if actor.role not in _STAFF:
        raise ForbiddenError("Доступно только менеджеру или администратору")


async def _load_tariff(db: AsyncSession, tariff_id: uuid.UUID) -> Tariff:
    result = await db.execute(
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
        .where(Tariff.id == tariff_id)
    )
    tariff = result.scalar_one_or_none()
    if not tariff:
        raise NotFoundError("Тариф не найден")
    return tariff


async def list_tariffs(
    db: AsyncSession,
    actor: TokenUser,
    include_archived: bool = False,
) -> list[Tariff]:
    _check_staff(actor)
    q = (
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
    )
    if not include_archived:
        q = q.where(Tariff.is_archived == False)  # noqa: E712
    q = q.order_by(Tariff.is_default.desc(), Tariff.created_at)
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_tariff_by_id(
    db: AsyncSession,
    tariff_id: uuid.UUID,
    actor: TokenUser,
) -> Tariff:
    _check_staff(actor)
    return await _load_tariff(db, tariff_id)


async def get_default_tariff(db: AsyncSession, actor: TokenUser) -> Tariff:
    """Public: any authenticated user can read the default tariff (for UI)."""
    result = await db.execute(
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
        .where(Tariff.is_default == True, Tariff.is_archived == False)  # noqa: E712
    )
    tariff = result.scalar_one_or_none()
    if not tariff:
        raise NotFoundError("Базовый тариф не настроен")
    return tariff


def _validate_fuel_prices(fuel_prices: list[dict]) -> None:
    """Ensure all FuelType values are covered and prices are positive."""
    provided = {fp["fuel_type"].upper() for fp in fuel_prices}
    missing = _VALID_FUEL_TYPES - provided
    if missing:
        raise ValidationError(
            f"Необходимо указать цену для всех типов топлива. Отсутствуют: {', '.join(sorted(missing))}"
        )
    for fp in fuel_prices:
        if Decimal(str(fp["price_per_liter"])) <= 0:
            raise ValidationError(f"Цена топлива должна быть больше 0 (fuel_type={fp['fuel_type']})")


def _validate_tiers(volume_tiers: list[dict]) -> None:
    for t in volume_tiers:
        if Decimal(str(t["min_volume"])) < 0:
            raise ValidationError("Минимальный объём ступени не может быть отрицательным")
        pct = Decimal(str(t["discount_pct"]))
        if not (0 <= pct <= 100):
            raise ValidationError("Скидка должна быть от 0 до 100%")


async def create_tariff(
    db: AsyncSession,
    actor: TokenUser,
    name: str,
    fuel_prices: list[dict],
    volume_tiers: list[dict],
    description: str | None = None,
) -> Tariff:
    _check_admin(actor)
    _validate_fuel_prices(fuel_prices)
    _validate_tiers(volume_tiers)

    # Check name uniqueness
    existing = await db.execute(select(Tariff).where(Tariff.name == name))
    if existing.scalar_one_or_none():
        raise ValidationError(f"Тариф с именем «{name}» уже существует")

    tariff = Tariff(
        id=uuid.uuid4(),
        name=name,
        description=description,
        is_default=False,
        created_by_id=actor.id,
    )
    db.add(tariff)
    await db.flush()

    for fp in fuel_prices:
        db.add(TariffFuelPrice(
            id=uuid.uuid4(),
            tariff_id=tariff.id,
            fuel_type=fp["fuel_type"].upper(),
            price_per_liter=Decimal(str(fp["price_per_liter"])),
        ))
    for t in volume_tiers:
        db.add(TariffVolumeTier(
            id=uuid.uuid4(),
            tariff_id=tariff.id,
            min_volume=Decimal(str(t["min_volume"])),
            discount_pct=Decimal(str(t["discount_pct"])),
        ))

    await db.flush()
    return await _load_tariff(db, tariff.id)


async def update_tariff(
    db: AsyncSession,
    tariff_id: uuid.UUID,
    actor: TokenUser,
    fuel_prices: list[dict],
    volume_tiers: list[dict],
    name: str | None = None,
    description: str | None = None,
) -> Tariff:
    tariff = await _load_tariff(db, tariff_id)

    if tariff.is_archived:
        raise ValidationError("Нельзя редактировать архивный тариф")

    # Manager may only edit the default tariff
    if actor.role == _MANAGER and not tariff.is_default:
        raise ForbiddenError("Менеджер может редактировать только базовый тариф")
    if actor.role not in _STAFF:
        raise ForbiddenError("Доступно только менеджеру или администратору")

    _validate_fuel_prices(fuel_prices)
    _validate_tiers(volume_tiers)

    if name and name != tariff.name:
        _check_admin(actor)  # only admin can rename
        existing = await db.execute(select(Tariff).where(Tariff.name == name, Tariff.id != tariff_id))
        if existing.scalar_one_or_none():
            raise ValidationError(f"Тариф с именем «{name}» уже существует")
        tariff.name = name

    if description is not None:
        tariff.description = description

    tariff.updated_at = datetime.now(timezone.utc)

    # Replace fuel_prices and volume_tiers wholesale
    for fp in tariff.fuel_prices:
        await db.delete(fp)
    for t in tariff.volume_tiers:
        await db.delete(t)
    await db.flush()

    for fp in fuel_prices:
        db.add(TariffFuelPrice(
            id=uuid.uuid4(),
            tariff_id=tariff.id,
            fuel_type=fp["fuel_type"].upper(),
            price_per_liter=Decimal(str(fp["price_per_liter"])),
        ))
    for t in volume_tiers:
        db.add(TariffVolumeTier(
            id=uuid.uuid4(),
            tariff_id=tariff.id,
            min_volume=Decimal(str(t["min_volume"])),
            discount_pct=Decimal(str(t["discount_pct"])),
        ))

    await db.flush()
    return await _load_tariff(db, tariff.id)


async def set_default_tariff(
    db: AsyncSession,
    tariff_id: uuid.UUID,
    actor: TokenUser,
) -> Tariff:
    _check_admin(actor)
    tariff = await _load_tariff(db, tariff_id)

    if tariff.is_archived:
        raise ValidationError("Нельзя назначить архивный тариф базовым")

    # Clear current default
    result = await db.execute(
        select(Tariff).where(Tariff.is_default == True)  # noqa: E712
    )
    current_default = result.scalar_one_or_none()
    if current_default and current_default.id != tariff_id:
        current_default.is_default = False

    tariff.is_default = True
    tariff.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return await _load_tariff(db, tariff_id)


async def archive_tariff(
    db: AsyncSession,
    tariff_id: uuid.UUID,
    actor: TokenUser,
) -> Tariff:
    _check_admin(actor)
    tariff = await _load_tariff(db, tariff_id)

    if tariff.is_default:
        raise ValidationError("Нельзя архивировать базовый тариф")

    if tariff.is_archived:
        raise ValidationError("Тариф уже архивирован")

    # Block if there are active orders on this tariff — order_service doesn't store
    # tariff_id on orders yet (future improvement), so we skip this check for now.
    # TODO: when tariff_snapshot_id is added to orders, block archiving if active orders exist.

    tariff.is_archived = True
    tariff.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return await _load_tariff(db, tariff_id)
