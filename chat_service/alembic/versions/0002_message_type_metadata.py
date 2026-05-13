"""messages: add msg_type and metadata columns

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-13

Adds support for document messages in chat.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("msg_type", sa.String(20), nullable=False, server_default="text"),
    )
    op.add_column(
        "messages",
        sa.Column("metadata", postgresql.JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "metadata")
    op.drop_column("messages", "msg_type")
