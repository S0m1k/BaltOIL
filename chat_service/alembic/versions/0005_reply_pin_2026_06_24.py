"""Правки 2026-06-24 — reply-to-message + закреп сообщений для всех.

Revision ID: 0005
Revises: 0004

Идемпотентно:
  messages.reply_to_id UUID NULL, FK messages.id ON DELETE SET NULL, индекс.
  messages.is_pinned BOOLEAN NOT NULL DEFAULT FALSE.
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS reply_to_id UUID NULL
    """)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'messages_reply_to_id_fkey'
            ) THEN
                ALTER TABLE messages
                    ADD CONSTRAINT messages_reply_to_id_fkey
                    FOREIGN KEY (reply_to_id) REFERENCES messages(id) ON DELETE SET NULL;
            END IF;
        END $$;
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_messages_reply_to_id ON messages (reply_to_id)
    """)
    op.execute("""
        ALTER TABLE messages
            ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS ix_messages_reply_to_id
    """)
    op.execute("""
        ALTER TABLE messages
            DROP CONSTRAINT IF EXISTS messages_reply_to_id_fkey
    """)
    op.execute("""
        ALTER TABLE messages
            DROP COLUMN IF EXISTS reply_to_id
    """)
    op.execute("""
        ALTER TABLE messages
            DROP COLUMN IF EXISTS is_pinned
    """)
