"""Правки 2026-06-11 — блокировка мессенджера для клиента (admin-only).

Revision ID: 0009
Revises: 0008

Идемпотентно: client_profiles.messenger_blocked BOOLEAN NOT NULL DEFAULT FALSE.
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE client_profiles
            ADD COLUMN IF NOT EXISTS messenger_blocked BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE client_profiles
            DROP COLUMN IF EXISTS messenger_blocked
    """)
