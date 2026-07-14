"""Правки 2026-07-14 — режим «только чаты» для клиента (admin-only toggle).

Revision ID: 0012
Revises: 0011

Идемпотентно: client_profiles.chats_only BOOLEAN NOT NULL DEFAULT FALSE.
Клиент с флагом видит в CRM только чаты и не может создавать заявки.
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE client_profiles
            ADD COLUMN IF NOT EXISTS chats_only BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE client_profiles
            DROP COLUMN IF EXISTS chats_only
    """)
