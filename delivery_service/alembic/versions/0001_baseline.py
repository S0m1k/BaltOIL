"""baseline

Revision ID: 0001
Revises:
Create Date: 2026-05-13

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
    # Enum types
    for name, values in [
        ("tripstatus", ["planned", "in_transit", "completed", "cancelled"]),
        ("transactiontype", ["arrival", "departure"]),
    ]:
        postgresql.ENUM(*values, name=name, create_type=True).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plate_number", sa.String(20), nullable=False, unique=True),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("capacity_liters", sa.Numeric(10, 2), nullable=False),
        sa.Column("assigned_driver_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_vehicles_plate_number", "vehicles", ["plate_number"], unique=True)
    op.create_index("ix_vehicles_assigned_driver_id", "vehicles", ["assigned_driver_id"])

    op.create_table(
        "trips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.Enum("planned", "in_transit", "completed", "cancelled", name="tripstatus"), nullable=False, server_default="planned"),
        sa.Column("volume_planned", sa.Numeric(10, 2), nullable=False),
        sa.Column("volume_actual", sa.Numeric(10, 2), nullable=True),
        sa.Column("departed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("arrived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_address", sa.Text(), nullable=True),
        sa.Column("driver_notes", sa.Text(), nullable=True),
        sa.Column("inv_fuel_type", sa.String(50), nullable=True),
        sa.Column("inv_order_number", sa.String(30), nullable=True),
        sa.Column("inv_client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("inv_client_name", sa.String(255), nullable=True),
        sa.Column("inv_driver_name", sa.String(255), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_trips_order_id", "trips", ["order_id"])
    op.create_index("ix_trips_driver_id", "trips", ["driver_id"])
    op.create_index("ix_trips_status", "trips", ["status"])

    op.create_table(
        "fuel_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.Enum("arrival", "departure", name="transactiontype"), nullable=False),
        sa.Column("fuel_type", sa.String(50), nullable=False),
        sa.Column("volume", sa.Numeric(12, 2), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_number", sa.String(30), nullable=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("driver_name", sa.String(255), nullable=True),
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_fuel_transactions_type", "fuel_transactions", ["type"])
    op.create_index("ix_fuel_transactions_fuel_type", "fuel_transactions", ["fuel_type"])
    op.create_index("ix_fuel_transactions_transaction_date", "fuel_transactions", ["transaction_date"])
    op.create_index("ix_fuel_transactions_trip_id", "fuel_transactions", ["trip_id"])

    op.create_table(
        "fuel_stock",
        sa.Column("fuel_type", sa.String(50), primary_key=True),
        sa.Column("current_volume", sa.Numeric(12, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fuel_stock")
    op.drop_table("fuel_transactions")
    op.drop_table("trips")
    op.drop_table("vehicles")
    op.execute("DROP TYPE IF EXISTS transactiontype")
    op.execute("DROP TYPE IF EXISTS tripstatus")
