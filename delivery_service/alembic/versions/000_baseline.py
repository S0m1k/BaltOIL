"""baseline: vehicles + trips + tripstatus enum

Revision ID: 000
Revises:
Create Date: 2026-05-27

Existing chain assumed trips/vehicles existed already. On fresh DBs the
chain failed at 001 because no migration ever created them. This baseline
fills the gap; on prod it never runs (already past head).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op


revision: str = "000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "trips" in sa.inspect(bind).get_table_names():
        # Старые БД могли создать trips вне alembic — пропускаем тихо.
        return

    postgresql.ENUM(
        "planned", "in_transit", "completed", "cancelled",
        name="tripstatus", create_type=True,
    ).create(bind, checkfirst=True)

    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plate_number", sa.String(20), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("capacity_liters", sa.Numeric(10, 2), nullable=False),
        sa.Column("assigned_driver_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("plate_number"),
    )
    op.create_index("ix_vehicles_plate_number", "vehicles", ["plate_number"], unique=True)
    op.create_index("ix_vehicles_assigned_driver_id", "vehicles", ["assigned_driver_id"])

    op.create_table(
        "trips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vehicles.id", ondelete="SET NULL"),
            nullable=False,  # made nullable in 002
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                "planned", "in_transit", "completed", "cancelled",
                name="tripstatus", create_type=False,
            ),
            nullable=False, server_default="planned",
        ),
        sa.Column("volume_planned", sa.Numeric(10, 2), nullable=False),
        sa.Column("volume_actual", sa.Numeric(10, 2), nullable=True),
        sa.Column("departed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_address", sa.Text(), nullable=True),
        sa.Column("driver_notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_trips_order_id", "trips", ["order_id"])
    op.create_index("ix_trips_driver_id", "trips", ["driver_id"])
    op.create_index("ix_trips_status", "trips", ["status"])


def downgrade() -> None:
    op.drop_table("trips")
    op.drop_table("vehicles")
    op.execute("DROP TYPE IF EXISTS tripstatus")
