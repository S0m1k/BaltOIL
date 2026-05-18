"""Partial unique index: at most one ringing/active call per conversation

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-18

Closes the race in start_call where two concurrent requests both pass the
"any active call?" check and both insert a new row. With this index, the
second INSERT fails with IntegrityError, which the service maps to 409.

Before applying, any existing duplicate ringing/active rows must be
closed — otherwise CREATE UNIQUE INDEX will itself fail.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defensive: close any existing duplicate active calls so the index can be built.
    # Keeps the most recently started row per conversation, marks the rest as missed.
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY conversation_id
                       ORDER BY started_at DESC
                   ) AS rn
            FROM calls
            WHERE status IN ('ringing', 'active')
        )
        UPDATE calls
        SET status = 'missed', ended_at = NOW()
        WHERE id IN (SELECT id FROM ranked WHERE rn > 1);
    """)

    op.execute("""
        CREATE UNIQUE INDEX uq_calls_one_active_per_conv
            ON calls (conversation_id)
            WHERE status IN ('ringing', 'active');
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_calls_one_active_per_conv;")
