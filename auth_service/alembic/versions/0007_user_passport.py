"""Add passport fields to users (driver) for POA (form M-2).

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-31

Спринт 2026-07 Деплой 3: паспортные данные водителя для рендера в доверенность.

Идемпотентно: ADD COLUMN IF NOT EXISTS.
"""
from alembic import op


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


COLUMNS = [
    ("passport_series",     "VARCHAR(4)"),
    ("passport_number",     "VARCHAR(6)"),
    ("passport_issued_by",  "VARCHAR(255)"),
    ("passport_issued_at",  "DATE"),
]


def upgrade() -> None:
    for name, ddl in COLUMNS:
        op.execute(
            f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {ddl} NULL"
        )


def downgrade() -> None:
    for name, _ in COLUMNS:
        op.execute(f"ALTER TABLE users DROP COLUMN IF EXISTS {name}")
