"""Правки заказчика 2026-06-11 — контактное лицо приёмки, согласование >= 3000 л,
индикация изменённых полей.

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-11

Идемпотентные изменения:
1. orders.contact_person_name  VARCHAR(120) NULL — контактное лицо для приёмки топлива
2. orders.contact_person_phone VARCHAR(20)  NULL — телефон контактного лица
3. orders.pending_changed_fields JSONB NULL — какие поля изменены до подтверждения водителем
4. Значение 'awaiting_manager' в enum orderstatus (на согласовании с менеджером)

Downgrade: дропает колонки; значение enum не удаляется (PostgreSQL не поддерживает
DROP VALUE — безопасно оставить).
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1-3. orders — новые колонки ──────────────────────────────────────────
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS contact_person_name    VARCHAR(120),
            ADD COLUMN IF NOT EXISTS contact_person_phone   VARCHAR(20),
            ADD COLUMN IF NOT EXISTS pending_changed_fields JSONB
    """)

    # ── 4. enum orderstatus += 'awaiting_manager' ────────────────────────────
    # ADD VALUE IF NOT EXISTS идемпотентен (PostgreSQL 12+); вне транзакции
    # alembic выполняет это через autocommit_block.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'awaiting_manager' BEFORE 'accepted'"
        )


def downgrade() -> None:
    op.execute("""
        ALTER TABLE orders
            DROP COLUMN IF EXISTS contact_person_name,
            DROP COLUMN IF EXISTS contact_person_phone,
            DROP COLUMN IF EXISTS pending_changed_fields
    """)
    # Значение enum 'awaiting_manager' намеренно не удаляется.
