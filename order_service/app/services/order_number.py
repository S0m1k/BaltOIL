"""
Atomic, race-condition-safe order number generation.

Uses a PostgreSQL upsert (INSERT ... ON CONFLICT DO UPDATE ... RETURNING)
to increment a per-year counter in a single round-trip with no race window.
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.order_counter import OrderYearCounter


async def generate_order_number(db: AsyncSession) -> str:
    year = datetime.now(timezone.utc).year

    stmt = (
        pg_insert(OrderYearCounter)
        .values(year=year, last_seq=1)
        .on_conflict_do_update(
            index_elements=["year"],
            set_={"last_seq": OrderYearCounter.last_seq + 1},
        )
        .returning(OrderYearCounter.last_seq)
    )
    result = await db.execute(stmt)
    seq: int = result.scalar_one()
    return f"ORD-{year}-{seq:06d}"
