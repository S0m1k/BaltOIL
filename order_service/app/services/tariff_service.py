"""Tariff CRUD service.

Access rules (enforced here, not in the router):
- Full CRUD по всем тарифам (создание, правка любых, архив, set-default,
  переименование, смена client_type): manager, admin.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tariff import (
    Tariff, TariffFuelPrice, TariffVolumeTier, TariffPriceHistory,
)
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.core.dependencies import TokenUser
from app.services import tariff_formula

_ADMIN = "admin"
_MANAGER = "manager"
_STAFF = {_ADMIN, _MANAGER}


def _check_staff(actor: TokenUser) -> None:
    if actor.role not in _STAFF:
        raise ForbiddenError("Доступно только менеджеру или администратору")


async def _attach_effective(db: AsyncSession, tariffs: list[Tariff]) -> None:
    """Проставить effective_fuel_prices (и base_tariff_name) на объекты тарифов.

    Для формульных тарифов цены выводятся из базового ПРИ ЧТЕНИИ — поэтому
    правка цен базового тарифа автоматически двигает все формульные.
    Атрибуты не отображены в ORM, поэтому в БД ничего не пишется.
    """
    base_ids = {t.base_tariff_id for t in tariffs if t.base_tariff_id}
    bases: dict[uuid.UUID, Tariff] = {}
    if base_ids:
        result = await db.execute(
            select(Tariff)
            .options(selectinload(Tariff.fuel_prices))
            .where(Tariff.id.in_(base_ids))
        )
        bases = {b.id: b for b in result.scalars().all()}

    for t in tariffs:
        base = bases.get(t.base_tariff_id) if t.base_tariff_id else None
        t.base_tariff_name = base.name if base else None
        if base is not None:
            t.effective_fuel_prices = tariff_formula.derive_price_rows(
                base.fuel_prices, t.fuel_prices, t.formula_type, t.formula_value
            )
        else:
            t.effective_fuel_prices = tariff_formula.normalize_rows(t.fuel_prices)


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
    await _attach_effective(db, [tariff])
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
    tariffs = list(result.scalars().all())
    await _attach_effective(db, tariffs)
    return tariffs


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
    await _attach_effective(db, [tariff])
    return tariff


async def list_default_tariffs(db: AsyncSession, actor: TokenUser) -> list[Tariff]:
    """Public: базовые (default) тарифы по всем типам клиентов — для модала
    «Базовые тарифы» на экране заявок (водители, менеджеры, админы)."""
    result = await db.execute(
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
        .where(Tariff.is_default == True, Tariff.is_archived == False)  # noqa: E712
        .order_by(Tariff.client_type)
    )
    tariffs = list(result.scalars().all())
    await _attach_effective(db, tariffs)
    return tariffs


def _validate_fuel_prices(fuel_prices: list[dict], is_formula: bool = False) -> None:
    """Правки CRM-33: цена обязательна ТОЛЬКО для видимых видов топлива.

    Скрытые (is_hidden=True) и вовсе не присланные виды цену не требуют —
    «глазик» в форме тарифа. У формульного тарифа собственных цен нет вовсе:
    они выводятся из базового, поэтому проверка цен не применяется.
    """
    if is_formula:
        return

    visible = [fp for fp in fuel_prices if not fp.get("is_hidden")]
    if not visible:
        raise ValidationError("Укажите цену хотя бы для одного вида топлива")

    for fp in visible:
        price = fp.get("price_per_liter")
        if price is None:
            raise ValidationError(
                f"Укажите цену для вида топлива {fp['fuel_type']} или скройте его"
            )
        if Decimal(str(price)) <= 0:
            raise ValidationError(f"Цена топлива должна быть больше 0 (fuel_type={fp['fuel_type']})")


def _validate_tiers(volume_tiers: list[dict]) -> None:
    for t in volume_tiers:
        if Decimal(str(t["min_volume"])) < 0:
            raise ValidationError("Минимальный объём ступени не может быть отрицательным")
        pct = Decimal(str(t["discount_pct"]))
        if not (0 <= pct <= 100):
            raise ValidationError("Скидка должна быть от 0 до 100%")


_VALID_CLIENT_TYPES = {None, "individual", "company"}


async def _validate_formula(
    db: AsyncSession,
    base_tariff_id: uuid.UUID | None,
    formula_type: str | None,
    formula_value: Decimal | None,
    self_id: uuid.UUID | None = None,
) -> None:
    """Проверить связку «формульный тариф → базовый» (CRM-33)."""
    if base_tariff_id is None:
        return
    if self_id is not None and base_tariff_id == self_id:
        raise ValidationError("Тариф не может считаться от самого себя")
    if formula_type not in tariff_formula.VALID_FORMULA_TYPES:
        raise ValidationError("Тип формулы должен быть «percent» или «fixed»")
    if formula_value is None:
        raise ValidationError("Укажите величину наценки или скидки")

    result = await db.execute(select(Tariff).where(Tariff.id == base_tariff_id))
    base = result.scalar_one_or_none()
    if base is None:
        raise NotFoundError("Базовый тариф для формулы не найден")
    if base.is_archived:
        raise ValidationError("Нельзя считать тариф от архивного базового тарифа")
    if base.base_tariff_id is not None:
        raise ValidationError("Базовым может быть только обычный тариф, не формульный")


def _add_price_rows(db: AsyncSession, tariff_id: uuid.UUID, fuel_prices: list[dict]) -> None:
    for fp in fuel_prices:
        price = fp.get("price_per_liter")
        db.add(TariffFuelPrice(
            id=uuid.uuid4(),
            tariff_id=tariff_id,
            fuel_type=fp["fuel_type"].upper(),
            price_per_liter=None if price is None else Decimal(str(price)),
            is_hidden=bool(fp.get("is_hidden", False)),
        ))


def _record_history(
    db: AsyncSession,
    tariff_id: uuid.UUID,
    actor: TokenUser,
    changes: list[dict],
) -> None:
    """Записать дифф цен в журнал (CRM-32). Пустой дифф ничего не пишет."""
    for ch in changes:
        db.add(TariffPriceHistory(
            id=uuid.uuid4(),
            tariff_id=tariff_id,
            fuel_type=ch["fuel_type"],
            change_kind=ch["change_kind"],
            old_price=ch["old_price"],
            new_price=ch["new_price"],
            changed_by_id=actor.id,
            changed_by_role=actor.role,
        ))


async def list_price_history(
    db: AsyncSession,
    tariff_id: uuid.UUID,
    actor: TokenUser,
    limit: int = 200,
) -> list[TariffPriceHistory]:
    """История изменения цен тарифа — новые сверху (CRM-32)."""
    _check_staff(actor)
    await _load_tariff(db, tariff_id)  # 404, если тарифа нет
    result = await db.execute(
        select(TariffPriceHistory)
        .where(TariffPriceHistory.tariff_id == tariff_id)
        .order_by(TariffPriceHistory.changed_at.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(result.scalars().all())


async def create_tariff(
    db: AsyncSession,
    actor: TokenUser,
    name: str,
    fuel_prices: list[dict],
    volume_tiers: list[dict],
    description: str | None = None,
    client_type: str | None = None,
    base_delivery_cost: Decimal = Decimal("0"),
    base_tariff_id: uuid.UUID | None = None,
    formula_type: str | None = None,
    formula_value: Decimal | None = None,
) -> Tariff:
    _check_staff(actor)
    is_formula = base_tariff_id is not None
    _validate_fuel_prices(fuel_prices, is_formula=is_formula)
    _validate_tiers(volume_tiers)
    await _validate_formula(db, base_tariff_id, formula_type, formula_value)
    if client_type not in _VALID_CLIENT_TYPES:
        raise ValidationError("client_type должен быть 'individual', 'company' или null")

    # Check name uniqueness
    existing = await db.execute(select(Tariff).where(Tariff.name == name))
    if existing.scalar_one_or_none():
        raise ValidationError(f"Тариф с именем «{name}» уже существует")

    tariff = Tariff(
        id=uuid.uuid4(),
        name=name,
        description=description,
        is_default=False,
        client_type=client_type,
        base_delivery_cost=Decimal(str(base_delivery_cost)),
        created_by_id=actor.id,
        base_tariff_id=base_tariff_id,
        formula_type=formula_type if is_formula else None,
        formula_value=(
            Decimal(str(formula_value)) if is_formula and formula_value is not None else None
        ),
    )
    db.add(tariff)
    await db.flush()

    _add_price_rows(db, tariff.id, fuel_prices)
    _record_history(
        db, tariff.id, actor,
        tariff_formula.diff_price_rows([], fuel_prices),
    )
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
    client_type: str | None = None,
    _client_type_set: bool = False,
    base_delivery_cost: Decimal | None = None,
    base_tariff_id: uuid.UUID | None = None,
    formula_type: str | None = None,
    formula_value: Decimal | None = None,
    _formula_set: bool = False,
) -> Tariff:
    tariff = await _load_tariff(db, tariff_id)

    if tariff.is_archived:
        raise ValidationError("Нельзя редактировать архивный тариф")

    _check_staff(actor)

    # Формула: применяется только если поля явно присланы, иначе остаётся как было
    if _formula_set:
        await _validate_formula(
            db, base_tariff_id, formula_type, formula_value, self_id=tariff_id
        )
        new_base_id = base_tariff_id
        new_formula_type = formula_type if base_tariff_id is not None else None
        new_formula_value = (
            Decimal(str(formula_value))
            if base_tariff_id is not None and formula_value is not None
            else None
        )
    else:
        new_base_id = tariff.base_tariff_id
        new_formula_type = tariff.formula_type
        new_formula_value = tariff.formula_value

    _validate_fuel_prices(fuel_prices, is_formula=new_base_id is not None)
    _validate_tiers(volume_tiers)

    # Дифф цен для журнала (CRM-32) — снимаем ДО удаления старых строк
    price_changes = tariff_formula.diff_price_rows(tariff.fuel_prices, fuel_prices)

    tariff.base_tariff_id = new_base_id
    tariff.formula_type = new_formula_type
    tariff.formula_value = new_formula_value

    if name and name != tariff.name:
        _check_staff(actor)
        existing = await db.execute(select(Tariff).where(Tariff.name == name, Tariff.id != tariff_id))
        if existing.scalar_one_or_none():
            raise ValidationError(f"Тариф с именем «{name}» уже существует")
        tariff.name = name

    if description is not None:
        tariff.description = description

    if base_delivery_cost is not None:
        tariff.base_delivery_cost = Decimal(str(base_delivery_cost))

    # client_type: staff may change it; _client_type_set=True means caller sent the field
    if _client_type_set:
        _check_staff(actor)
        if client_type not in _VALID_CLIENT_TYPES:
            raise ValidationError("client_type должен быть 'individual', 'company' или null")
        tariff.client_type = client_type

    tariff.updated_at = datetime.now(timezone.utc)

    # Replace fuel_prices and volume_tiers wholesale
    for fp in tariff.fuel_prices:
        await db.delete(fp)
    for t in tariff.volume_tiers:
        await db.delete(t)
    await db.flush()

    _add_price_rows(db, tariff.id, fuel_prices)
    _record_history(db, tariff.id, actor, price_changes)
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
    _check_staff(actor)
    tariff = await _load_tariff(db, tariff_id)

    if tariff.is_archived:
        raise ValidationError("Нельзя назначить архивный тариф базовым")

    # Clear current default only for the SAME client_type (one default per client_type)
    result = await db.execute(
        select(Tariff).where(
            Tariff.is_default == True,  # noqa: E712
            Tariff.client_type == tariff.client_type,
        )
    )
    for current_default in result.scalars().all():
        if current_default.id != tariff_id:
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
    _check_staff(actor)
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
