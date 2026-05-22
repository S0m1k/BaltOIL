"""Rebuild conversation model: add kind/client_id/driver_id/order_id/group_code.

All existing messages and conversations are wiped — production data is ephemeral test data
(see SPEC_SPRINT_2026_05.md §3.0). The new model uses snapshot-based membership instead
of the participants_hash approach.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Wipe all chat data — new conversation model is incompatible with old one
    op.execute("TRUNCATE TABLE messages, conversation_participants, conversations CASCADE")

    # Drop old columns / constraint — all IF EXISTS so re-runs are safe
    op.execute(
        "ALTER TABLE conversations DROP CONSTRAINT IF EXISTS uq_conversation_participants_hash"
    )
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS participants_hash")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS type")
    op.execute("DROP TYPE IF EXISTS conversationtype")

    # Add new discriminator column — IF NOT EXISTS makes this idempotent on re-run
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN IF NOT EXISTS kind VARCHAR(30) NOT NULL DEFAULT 'client_manager'"
    )
    # Drop the server default now that the column is populated
    op.execute(
        "ALTER TABLE conversations ALTER COLUMN kind DROP DEFAULT"
    )

    # Snapshot fields — stored directly so membership checks need no extra RPC
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS client_id UUID")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS driver_id UUID")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS order_id  UUID")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS group_code VARCHAR(30)")

    # Partial unique indexes enforce the one-per-entity invariants
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_client_manager "
        "ON conversations (client_id) WHERE kind = 'client_manager'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_client_driver_order "
        "ON conversations (order_id) WHERE kind = 'client_driver_order'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_conv_staff_group "
        "ON conversations (group_code) WHERE kind = 'staff_group'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_conv_client_manager")
    op.execute("DROP INDEX IF EXISTS uq_conv_client_driver_order")
    op.execute("DROP INDEX IF EXISTS uq_conv_staff_group")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS group_code")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS order_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS driver_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS client_id")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS kind")
    op.execute("CREATE TYPE IF NOT EXISTS conversationtype AS ENUM ('client_support', 'internal')")
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN IF NOT EXISTS type conversationtype NOT NULL DEFAULT 'client_support'"
    )
    op.execute("ALTER TABLE conversations ALTER COLUMN type DROP DEFAULT")
    op.execute("ALTER TABLE conversations ADD COLUMN IF NOT EXISTS participants_hash VARCHAR(64)")
    op.execute(
        "ALTER TABLE conversations "
        "ADD CONSTRAINT uq_conversation_participants_hash UNIQUE (participants_hash)"
    )
