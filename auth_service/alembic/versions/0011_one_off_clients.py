"""Правки 2026-07-11 — разовые клиенты (создаются менеджером/водителем при заявке).

Revision ID: 0011
Revises: 0010

Идемпотентно: client_profiles.is_one_off BOOLEAN NOT NULL DEFAULT FALSE.
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE client_profiles
            ADD COLUMN IF NOT EXISTS is_one_off BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE client_profiles
            DROP COLUMN IF EXISTS is_one_off
    """)
