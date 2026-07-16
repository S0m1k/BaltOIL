"""Правки 2026-07-14 (вечер) — ручной расход топлива «в бак / иное».

Revision ID: 006
Revises: 005

1. fuel_transactions.expense_kind VARCHAR(20) NULL — маркировка ручного
   расхода: 'tank_refuel' (в бак) | 'other' (иное). NULL у автоматических
   списаний по рейсам и приходов.
2. tanktxkind + значение 'expense' — списание из ёмкости не по заявке.

Идемпотентно.
"""
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE fuel_transactions
            ADD COLUMN IF NOT EXISTS expense_kind VARCHAR(20) NULL
    """)
    # PG >= 12 допускает ADD VALUE в транзакции (тип создан ранее)
    op.execute("ALTER TYPE tanktxkind ADD VALUE IF NOT EXISTS 'expense'")


def downgrade() -> None:
    op.execute("ALTER TABLE fuel_transactions DROP COLUMN IF EXISTS expense_kind")
    # Удаление значения из enum PostgreSQL не поддерживает — оставляем.
