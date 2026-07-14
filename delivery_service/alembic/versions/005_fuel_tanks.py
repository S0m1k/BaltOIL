"""Правки 2026-07-14 — ёмкости хранения топлива со счётчиками колонок.

Revision ID: 005
Revises: 004
Create Date: 2026-07-14

Идемпотентно: fuel_tanks + tank_transactions (append-only журнал операций).
"""
from typing import Sequence, Union
from alembic import op


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fuel_tanks (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name           VARCHAR(100)  NOT NULL,
            fuel_type      VARCHAR(50)   NOT NULL,
            current_volume NUMERIC(12,2) NOT NULL DEFAULT 0,
            counter        NUMERIC(10,0) NOT NULL DEFAULT 0,
            is_active      BOOLEAN       NOT NULL DEFAULT TRUE,
            created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_fuel_tanks_fuel_type ON fuel_tanks (fuel_type)")

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE tanktxkind AS ENUM
                ('arrival', 'issue', 'transfer_in', 'transfer_out', 'adjust');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS tank_transactions (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tank_id        UUID          NOT NULL REFERENCES fuel_tanks(id) ON DELETE CASCADE,
            kind           tanktxkind    NOT NULL,
            volume         NUMERIC(12,2) NOT NULL,
            counter_before NUMERIC(10,0),
            counter_after  NUMERIC(10,0),
            order_id       UUID,
            order_number   VARCHAR(30),
            peer_tank_id   UUID,
            actor_id       UUID          NOT NULL,
            actor_name     VARCHAR(255),
            notes          TEXT,
            created_at     TIMESTAMPTZ   NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_tank_transactions_tank_id ON tank_transactions (tank_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tank_transactions_kind ON tank_transactions (kind)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tank_transactions_order_id ON tank_transactions (order_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tank_transactions_created_at ON tank_transactions (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tank_transactions")
    op.execute("DROP TABLE IF EXISTS fuel_tanks")
    op.execute("DROP TYPE IF EXISTS tanktxkind")
