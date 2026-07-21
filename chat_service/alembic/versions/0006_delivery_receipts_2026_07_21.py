"""Правки 2026-07-21 — статусы сообщений (доставлено/прочитано).

Revision ID: 0006
Revises: 0005

Идемпотентно:
  conversation_participants.last_delivered_at TIMESTAMPTZ NULL — момент, когда
  участник в последний раз «получил» сообщения диалога (открыл список чатов /
  подключился по WS / открыл диалог). Вместе с уже существующим last_read_at
  даёт трёхстатусную индикацию у отправителя: отправлено / доставлено / прочитано.
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_participants
            ADD COLUMN IF NOT EXISTS last_delivered_at TIMESTAMPTZ NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE conversation_participants
            DROP COLUMN IF EXISTS last_delivered_at
    """)
