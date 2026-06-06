"""Deploy 3 — Поля зоны доставки в заявках + base_delivery_cost в тарифах

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-06

Идемпотентные изменения:
1. Добавить base_delivery_cost (NUMERIC 12,2, default 0) в таблицу tariffs.
2. Добавить 5 полей в таблицу orders:
   - delivery_lat  NUMERIC(10,7) NULL
   - delivery_lon  NUMERIC(10,7) NULL
   - delivery_zone_id   UUID NULL
   - delivery_zone_name VARCHAR(120) NULL
   - delivery_cost NUMERIC(12,2) NULL

Downgrade: дропает добавленные колонки.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. tariffs.base_delivery_cost ─────────────────────────────────────────
    op.execute("""
        ALTER TABLE tariffs
            ADD COLUMN IF NOT EXISTS base_delivery_cost NUMERIC(12,2) NOT NULL DEFAULT 0
    """)

    # ── 2. orders — поля зоны доставки ───────────────────────────────────────
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS delivery_lat       NUMERIC(10,7),
            ADD COLUMN IF NOT EXISTS delivery_lon       NUMERIC(10,7),
            ADD COLUMN IF NOT EXISTS delivery_zone_id   UUID,
            ADD COLUMN IF NOT EXISTS delivery_zone_name VARCHAR(120),
            ADD COLUMN IF NOT EXISTS delivery_cost      NUMERIC(12,2)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orders
            DROP COLUMN IF EXISTS delivery_lat,
            DROP COLUMN IF EXISTS delivery_lon,
            DROP COLUMN IF EXISTS delivery_zone_id,
            DROP COLUMN IF EXISTS delivery_zone_name,
            DROP COLUMN IF EXISTS delivery_cost
    """)
    op.execute("""
        ALTER TABLE tariffs
            DROP COLUMN IF EXISTS base_delivery_cost
    """)
