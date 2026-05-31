"""Sprint 2026-07 Deploy 2: contracts + contract_month_counters

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-31

Изменения (все идемпотентные — деплой катится на живую БД):
1. CREATE TYPE contractstatus (active|terminated|expired) — через guard.
2. CREATE TABLE IF NOT EXISTS contracts — договор поставки, живёт на клиенте.
3. CREATE TABLE IF NOT EXISTS contract_month_counters — атомарный счётчик NNN/MM.
4. ADD VALUE 'contract' в enum documenttype (для агрегации документов клиента).

Договор не привязан к заявке (order_id нет) — отдельная таблица, не documents.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. enum contractstatus (guard — CREATE TYPE не поддерживает IF NOT EXISTS)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'contractstatus') THEN
                CREATE TYPE contractstatus AS ENUM ('active', 'terminated', 'expired');
            END IF;
        END $$;
    """)

    # 2. Таблица договоров
    op.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id UUID PRIMARY KEY,
            client_id UUID NOT NULL,
            contract_number VARCHAR(20) NOT NULL UNIQUE,
            seller_snapshot JSONB NOT NULL,
            buyer_snapshot JSONB NOT NULL,
            signed_at DATE NULL,
            effective_until DATE NULL,
            status contractstatus NOT NULL DEFAULT 'active',
            file_path TEXT NULL,
            created_by_id UUID NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_contracts_client_id ON contracts (client_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contracts_contract_number ON contracts (contract_number)")

    # 3. Счётчик номеров договоров по месяцам
    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_month_counters (
            month_key VARCHAR(7) PRIMARY KEY,
            last_seq INTEGER NOT NULL DEFAULT 0
        )
    """)

    # 4. Значение 'contract' в documenttype (idempotent)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'contract'
                  AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'documenttype')
            ) THEN
                ALTER TYPE documenttype ADD VALUE 'contract';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # enum-значение 'contract' в documenttype не убираем (PG не поддерживает DROP VALUE).
    op.execute("DROP TABLE IF EXISTS contract_month_counters")
    op.execute("DROP TABLE IF EXISTS contracts")
    op.execute("DROP TYPE IF EXISTS contractstatus")
