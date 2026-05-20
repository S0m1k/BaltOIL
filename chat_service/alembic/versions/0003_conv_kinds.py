"""Rebuild conversation model: add kind/client_id/driver_id/order_id/group_code.

All existing messages and conversations are wiped — production data is ephemeral test data
(see SPEC_SPRINT_2026_05.md §3.0). The new model uses snapshot-based membership instead
of the participants_hash approach.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Wipe all chat data — new conversation model is incompatible with old one
    op.execute("TRUNCATE TABLE messages, conversation_participants, conversations CASCADE")

    # Drop old columns that are replaced by the new model
    op.drop_constraint("uq_conversation_participants_hash", "conversations", type_="unique")
    op.drop_column("conversations", "participants_hash")
    op.drop_column("conversations", "type")
    op.execute("DROP TYPE IF EXISTS conversationtype")

    # Add new discriminator column: client_manager | client_driver_order | staff_group
    op.add_column(
        "conversations",
        sa.Column("kind", sa.String(30), nullable=False, server_default="client_manager"),
    )
    op.alter_column("conversations", "kind", server_default=None)

    # Snapshot fields — stored directly so membership checks need no extra RPC
    op.add_column("conversations", sa.Column("client_id", PG_UUID(as_uuid=True), nullable=True))
    op.add_column("conversations", sa.Column("driver_id", PG_UUID(as_uuid=True), nullable=True))
    op.add_column("conversations", sa.Column("order_id",  PG_UUID(as_uuid=True), nullable=True))
    op.add_column("conversations", sa.Column("group_code", sa.String(30), nullable=True))

    # Partial unique indexes enforce the one-per-entity invariants
    op.execute(
        "CREATE UNIQUE INDEX uq_conv_client_manager "
        "ON conversations (client_id) WHERE kind = 'client_manager'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_conv_client_driver_order "
        "ON conversations (order_id) WHERE kind = 'client_driver_order'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_conv_staff_group "
        "ON conversations (group_code) WHERE kind = 'staff_group'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_conv_client_manager")
    op.execute("DROP INDEX IF EXISTS uq_conv_client_driver_order")
    op.execute("DROP INDEX IF EXISTS uq_conv_staff_group")
    op.drop_column("conversations", "group_code")
    op.drop_column("conversations", "order_id")
    op.drop_column("conversations", "driver_id")
    op.drop_column("conversations", "client_id")
    op.drop_column("conversations", "kind")
    op.execute("CREATE TYPE conversationtype AS ENUM ('client_support', 'internal')")
    op.add_column(
        "conversations",
        sa.Column("type", sa.Enum("client_support", "internal", name="conversationtype"), nullable=False,
                  server_default="client_support"),
    )
    op.alter_column("conversations", "type", server_default=None)
    op.add_column("conversations", sa.Column("participants_hash", sa.String(64), nullable=True))
    op.create_unique_constraint(
        "uq_conversation_participants_hash", "conversations", ["participants_hash"]
    )
