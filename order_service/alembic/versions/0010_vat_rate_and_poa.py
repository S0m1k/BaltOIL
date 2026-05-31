"""Sprint 2026-07 Deploy 3: vat_rate в legal_entities + значение poa в documenttype

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-31

Изменения (идемпотентные):
1. ADD COLUMN IF NOT EXISTS vat_rate INT NOT NULL DEFAULT 22 в legal_entities.
2. ADD VALUE 'poa' в enum documenttype (доверенность М-2).
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE legal_entities "
        "ADD COLUMN IF NOT EXISTS vat_rate INTEGER NOT NULL DEFAULT 22"
    )
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'poa'
                  AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'documenttype')
            ) THEN
                ALTER TYPE documenttype ADD VALUE 'poa';
            END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE legal_entities DROP COLUMN IF EXISTS vat_rate")
    # enum-значение 'poa' не убираем (PG не поддерживает DROP VALUE).
