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

log = logging.getLogger(__name__)

_CENT = Decimal("0.01")


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

    fuel_key = str(fuel_type).upper()
    price_row = next(
        (fp for fp in tariff.fuel_prices if fp.fuel_type.upper() == fuel_key),
        None,
    )
    if price_row is None:
        return {
            "tariff_found": False,
            "price_per_liter": None,
            "discount_pct": Decimal("0"),
            "effective_price_per_liter": None,
            "fuel_subtotal": None,
            "base_delivery_cost": Decimal(str(tariff.base_delivery_cost)) if tariff.base_delivery_cost else None,
        }

    price = Decimal(str(price_row.price_per_liter))
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

    # Find price for this fuel type (fuel_type is now a plain str code)
    fuel_key = str(fuel_type).upper()
    price_row = next(
        (fp for fp in tariff.fuel_prices if fp.fuel_type.upper() == fuel_key),
        None,
    )
    if price_row is None:
        log.warning(
            "Tariff %s has no price for fuel_type=%s — skipping expected_amount",
            tariff.id, fuel_key,
        )
        return None

    price = Decimal(str(price_row.price_per_liter))
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
