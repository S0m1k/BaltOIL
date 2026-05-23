"""Add OKPO column to legal_entities

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-23

ОКПО (Общероссийский классификатор предприятий и организаций) — обязателен
в УПД и ТТН. Идемпотентная миграция: ADD COLUMN IF NOT EXISTS.
"""

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

from alembic import op


def upgrade() -> None:
    op.execute(
        "ALTER TABLE legal_entities "
        "ADD COLUMN IF NOT EXISTS okpo VARCHAR(10) NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE legal_entities DROP COLUMN IF EXISTS okpo")
