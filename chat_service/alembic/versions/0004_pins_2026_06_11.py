"""Правки 2026-06-11 — закрепление чатов.

Revision ID: 0004
Revises: 0003

Идемпотентно: conversation_participants.is_pinned BOOLEAN NOT NULL DEFAULT FALSE.
Kind client_accountant хранится в строковой колонке kind — миграция не нужна.
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_participants
            ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_participants
            DROP COLUMN IF EXISTS is_pinned
    """)
