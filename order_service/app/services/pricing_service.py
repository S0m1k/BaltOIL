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

from app.models.order import FuelType
from app.models.tariff import Tariff, TariffFuelPrice

log = logging.getLogger(__name__)

_CENT = Decimal("0.01")


async def get_default_tariff(db: AsyncSession) -> Tariff | None:
    result = await db.execute(
        select(Tariff)
        .options(
            selectinload(Tariff.fuel_prices),
            selectinload(Tariff.volume_tiers),
        )
        .where(Tariff.is_default == True, Tariff.is_archived == False)  # noqa: E712
    )
    return result.scalar_one_or_none()


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


async def compute_expected_amount(
    db: AsyncSession,
    fuel_type: FuelType,
    volume: float,
    tariff_id: uuid.UUID | None,
) -> Decimal | None:
    """Return computed expected_amount or None if tariff is not configured."""
    tariff = (
        await get_tariff(db, tariff_id)
        if tariff_id
        else await get_default_tariff(db)
    )
    if tariff is None:
        log.warning("No active tariff found (tariff_id=%s) — skipping expected_amount", tariff_id)
        return None

    # Find price for this fuel type
    fuel_key = fuel_type.value.upper() if hasattr(fuel_type, "value") else str(fuel_type).upper()
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

    # Pick the best (highest applicable) discount tier
    discount_pct = Decimal("0")
    for tier in sorted(tariff.volume_tiers, key=lambda t: t.min_volume, reverse=True):
        if vol >= Decimal(str(tier.min_volume)):
            discount_pct = Decimal(str(tier.discount_pct))
            break

    effective_price = price * (1 - discount_pct / 100)
    return (effective_price * vol).quantize(_CENT, rounding=ROUND_HALF_UP)
