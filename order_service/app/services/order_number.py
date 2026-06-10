"""
Atomic, race-condition-safe order number generation.

Uses a PostgreSQL upsert (INSERT ... ON CONFLICT DO UPDATE ... RETURNING)
to increment a per-kind counter in a single round-trip with no race window.

Number format:
  individual → ф{n}
  company    → ю{n}
  ttn_l      → л{n}
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.order import OrderKind
from app.models.order_counter import OrderKindCounter

_KIND_PREFIX: dict[str, str] = {
    OrderKind.INDIVIDUAL.value: "ф",
    OrderKind.COMPANY.value:    "ю",
    OrderKind.TTN_L.value:      "л",
}


async def generate_order_number(db: AsyncSession, kind: OrderKind) -> str:
    kind_val = kind.value if hasattr(kind, "value") else str(kind)

    stmt = (
        pg_insert(OrderKindCounter)
        .values(kind=kind_val, last_seq=1)
        .on_conflict_do_update(
            index_elements=["kind"],
            set_={"last_seq": OrderKindCounter.last_seq + 1},
        )
        .returning(OrderKindCounter.last_seq)
    )
    result = await db.execute(stmt)
    seq: int = result.scalar_one()
    prefix = _KIND_PREFIX.get(kind_val, kind_val)
    return f"{prefix}{seq}"


async def generate_ttn_number(db: AsyncSession) -> str:
    """Атомарный сквозной номер ТТН с годовым сбросом: ТТН-{год}-{NNNNNN}.

    Переиспользуем OrderKindCounter (key→seq) с ключом ttn-{год} — без миграции.
    """
    from datetime import datetime, timezone
    year = datetime.now(timezone.utc).year
    key = f"ttn-{year}"
    stmt = (
        pg_insert(OrderKindCounter)
        .values(kind=key, last_seq=1)
        .on_conflict_do_update(
            index_elements=["kind"],
            set_={"last_seq": OrderKindCounter.last_seq + 1},
        )
        .returning(OrderKindCounter.last_seq)
    )
    result = await db.execute(stmt)
    seq: int = result.scalar_one()
    return f"ТТН-{year}-{seq:06d}"
