"""baseline — calls & call_participants

Revision ID: 0001
Revises:
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    postgresql.ENUM(
        "ringing", "active", "ended", "missed",
        name="callstatus", create_type=True,
    ).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_name", sa.String(64), nullable=False),
        sa.Column("initiated_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("initiated_by_name", sa.String(255), nullable=False),
        sa.Column(
            "status",
            sa.Enum("ringing", "active", "ended", "missed", name="callstatus"),
            nullable=False,
            server_default="ringing",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("room_name", name="uq_calls_room_name"),
    )
    op.create_index("ix_calls_conversation_id", "calls", ["conversation_id"])
    op.create_index("ix_calls_room_name", "calls", ["room_name"])
    op.create_index("ix_calls_status", "calls", ["status"])

    op.create_table(
        "call_participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "call_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("calls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("user_role", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_call_participants_call_id", "call_participants", ["call_id"])
    op.create_index("ix_call_participants_user_id", "call_participants", ["user_id"])


def downgrade() -> None:
    op.drop_table("call_participants")
    op.drop_table("calls")
    op.execute("DROP TYPE IF EXISTS callstatus")
