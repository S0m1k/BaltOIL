"""Mobile offline-outbox idempotency — add idempotency_keys table.

Revision ID: 0022_idempotency_keys
Revises: 0021_contract_global_counter
Create Date: 2026-06-14

Idempotent: uses CREATE TABLE IF NOT EXISTS — safe to re-run.

Stores one row per processed idempotency key so that retried offline
mutations (record_payment / transition_status) return the original result
without re-executing side effects.

Downgrade: drops the table (no cascade; referenced ids are logical, no FK).
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0022_idempotency_keys"
down_revision: Union[str, None] = "0021_contract_global_counter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            key         VARCHAR(64)  PRIMARY KEY,
            operation   VARCHAR(64)  NOT NULL,
            order_id    UUID,
            payment_id  UUID,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    # Index for fast key lookup (already covered by PK, but explicit for clarity)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_idempotency_keys_key
            ON idempotency_keys (key)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
