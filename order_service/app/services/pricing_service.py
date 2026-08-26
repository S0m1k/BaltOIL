"""Pricing: compute expected_amount for an order using client's tariff.

Formula:
    effective_price = base_price_per_liter × (1 - discount_pct / 100)
    expected_amount = effective_price × volume, rounded to 2 decimal places.

Discount tier: highest min_volume ≤ actual volume wins. If no tiers match, 0% discount.
"""
import uuid
import logging
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.tariff import Tariff, TariffFuelPrice
from app.services import tariff_formula

log = logging.getLogger(__name__)

_CENT = Decimal("0.01")


async def resolve_fuel_price(
    db: AsyncSession, tariff: Tariff, fuel_type: str
) -> Decimal | None:
    """Действующая цена ₽/л по тарифу для вида топлива, либо None.

    Учитывает правки CRM-33:
    - скрытые виды («глазик» выключен) недоступны для заказа → None;
    - формульный тариф считает цену от базового ПРИ ЧТЕНИИ, поэтому правка
      цен базового тарифа автоматически двигает все формульные.
    """
    fuel_key = str(fuel_type).upper()

    if tariff.base_tariff_id:
        base = await get_tariff(db, tariff.base_tariff_id)
        if base is None:
            log.warning(
                "Formula tariff %s: base tariff %s missing/archived",
                tariff.id, tariff.base_tariff_id,
            )
            return None
        rows = tariff_formula.derive_price_rows(
            base.fuel_prices, tariff.fuel_prices, tariff.formula_type, tariff.formula_value
        )
    else:
        rows = tariff_formula.normalize_rows(tariff.fuel_prices)

    return tariff_formula.visible_prices(rows).get(fuel_key)


async def get_default_tariff(db: AsyncSession, client_type: str | None = None) -> Tariff | None:
    """Return the default tariff, preferring one that matches client_type.

    Lookup order:
    1. is_default & not archived & client_type == given (exact match)
    2. is_default & not archived & client_type IS NULL (generic default)
    3. any is_default & not archived (last resort)
    """
    base = (
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
        .where(Tariff.is_default == True, Tariff.is_archived == False)  # noqa: E712
    )

    if client_type is not None:
        # 1. Exact match
        result = await db.execute(base.where(Tariff.client_type == client_type))
        tariff = result.scalar_one_or_none()
        if tariff is not None:
            return tariff
        # 2. Generic (NULL) default
        result = await db.execute(base.where(Tariff.client_type.is_(None)))
        tariff = result.scalar_one_or_none()
        if tariff is not None:
            return tariff

    # 3. Any default (original behaviour / fallback)
    result = await db.execute(base)
    return result.scalars().first()


async def get_tariff(db: AsyncSession, tariff_id: uuid.UUID) -> Tariff | None:
    result = await db.execute(
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
        .where(Tariff.id == tariff_id, Tariff.is_archived == False)  # noqa: E712
    )
    return result.scalar_one_or_none()


# Наценка НДС на доставку для юрлиц (правки 2026-07-22): цены зон в рублях
# заданы для физлиц; юрлицо платит и видит цену ×1.22 (3500 → 4270).
LEGAL_DELIVERY_VAT = Decimal("1.22")


def compute_zone_delivery_cost(
    zone_info: dict,
    rate_per_liter,
    volume: float,
    delivery_coefficient: float = 1.0,
    client_type: str = "individual",
) -> "Decimal | None":
    """Стоимость доставки для найденной зоны (правки 2026-06-11).

    Если у зоны задана фиксированная цена delivery_price (₽) — используется она
    (умноженная на клиентский delivery_coefficient). Иначе — legacy-формула
    rate_per_liter × volume × cost_coefficient × delivery_coefficient.
    Для юрлиц (client_type="company") итог дополнительно ×LEGAL_DELIVERY_VAT.
    """
    price = zone_info.get("delivery_price")
    if price is not None:
        cost = Decimal(str(price)) * Decimal(str(delivery_coefficient))
    else:
        cost = compute_delivery_cost(
            rate_per_liter, volume, zone_info["cost_coefficient"], delivery_coefficient
        )
        if cost is None:
            return None
    if client_type == "company":
        cost = cost * LEGAL_DELIVERY_VAT
    return cost.quantize(_CENT, rounding=ROUND_HALF_UP)


def compute_delivery_cost(
    rate_per_liter,
    volume: float,
    zone_coef,
    delivery_coefficient: float = 1.0,
) -> "Decimal | None":
    """Compute delivery cost = rate_per_liter × volume × zone_coef × delivery_coefficient.

    Returns None if rate_per_liter is None or 0 (delivery cost not configured).
    """
    if rate_per_liter is None:
        return None
    rate = Decimal(str(rate_per_liter))
    if rate == Decimal("0"):
        return None
    return (
        rate
        * Decimal(str(volume))
        * Decimal(str(zone_coef))
        * Decimal(str(delivery_coefficient))
    ).quantize(_CENT, rounding=ROUND_HALF_UP)


async def compute_price_breakdown(
    db: AsyncSession,
    fuel_type: str,
    volume: float,
    tariff_id: uuid.UUID | None,
    client_type: str | None = None,
    fuel_coefficient: float = 1.0,
) -> dict:
    """Return a detailed price breakdown dict (no DB writes).

    Keys: tariff_found, price_per_liter, discount_pct, effective_price_per_liter,
          fuel_subtotal, base_delivery_cost.
    All money values are Decimal | None; discount_pct is Decimal (0 if none).
    fuel_coefficient multiplies the effective price (per-client fuel price adjustment).
    base_delivery_cost is the per-liter delivery rate (₽/л) stored on the tariff.
    """
    tariff = (
        await get_tariff(db, tariff_id)
        if tariff_id
        else await get_default_tariff(db, client_type)
    )
    if tariff is None:
        return {
            "tariff_found": False,
            "price_per_liter": None,
            "discount_pct": Decimal("0"),
            "effective_price_per_liter": None,
            "fuel_subtotal": None,
            "base_delivery_cost": None,
        }

    price = await resolve_fuel_price(db, tariff, fuel_type)
    if price is None:
        return {
            "tariff_found": False,
            "price_per_liter": None,
            "discount_pct": Decimal("0"),
            "effective_price_per_liter": None,
            "fuel_subtotal": None,
            "base_delivery_cost": Decimal(str(tariff.base_delivery_cost)) if tariff.base_delivery_cost else None,
        }

    vol = Decimal(str(volume))
    fc = Decimal(str(fuel_coefficient))

    discount_pct = Decimal("0")
    for tier in sorted(tariff.volume_tiers, key=lambda t: t.min_volume, reverse=True):
        if vol >= Decimal(str(tier.min_volume)):
            discount_pct = Decimal(str(tier.discount_pct))
            break

    effective_price = price * (1 - discount_pct / 100) * fc
    fuel_subtotal = (effective_price * vol).quantize(_CENT, rounding=ROUND_HALF_UP)
    base_delivery_cost = Decimal(str(tariff.base_delivery_cost)) if tariff.base_delivery_cost else None

    return {
        "tariff_found": True,
        "price_per_liter": price,
        "discount_pct": discount_pct,
        "effective_price_per_liter": effective_price.quantize(_CENT, rounding=ROUND_HALF_UP),
        "fuel_subtotal": fuel_subtotal,
        "base_delivery_cost": base_delivery_cost,
    }


async def compute_expected_amount(
    db: AsyncSession,
    fuel_type: str,
    volume: float,
    tariff_id: uuid.UUID | None,
    client_type: str | None = None,
    fuel_coefficient: float = 1.0,
) -> Decimal | None:
    """Return computed expected_amount (fuel only) or None if tariff is not configured.

    fuel_coefficient multiplies the effective price per liter (per-client adjustment).
    """
    tariff = (
        await get_tariff(db, tariff_id)
        if tariff_id
        else await get_default_tariff(db, client_type)
    )
    if tariff is None:
        log.warning("No active tariff found (tariff_id=%s) — skipping expected_amount", tariff_id)
        return None

    # Find price for this fuel type (учитывает «глазик» и формульные тарифы)
    price = await resolve_fuel_price(db, tariff, fuel_type)
    if price is None:
        log.warning(
            "Tariff %s has no visible price for fuel_type=%s — skipping expected_amount",
            tariff.id, str(fuel_type).upper(),
        )
        return None

    vol = Decimal(str(volume))
    fc = Decimal(str(fuel_coefficient))

    # Pick the best (highest applicable) discount tier
    discount_pct = Decimal("0")
    for tier in sorted(tariff.volume_tiers, key=lambda t: t.min_volume, reverse=True):
        if vol >= Decimal(str(tier.min_volume)):
            discount_pct = Decimal(str(tier.discount_pct))
            break

    effective_price = price * (1 - discount_pct / 100) * fc
    return (effective_price * vol).quantize(_CENT, rounding=ROUND_HALF_UP)
