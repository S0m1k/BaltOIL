"""Add inventory tables and inv_* columns to trips

Revision ID: 001
Revises:
Create Date: 2026-05-09

Adds:
  - Table: fuel_transactions
  - Table: fuel_stock
  - Columns to trips: inv_fuel_type, inv_order_number, inv_client_id,
                      inv_client_name, inv_driver_name
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── New table: fuel_stock ──────────────────────────────────────────
    op.create_table(
        "fuel_stock",
        sa.Column("fuel_type", sa.String(50), nullable=False),
        sa.Column("current_volume", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column(
            "last_updated",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("fuel_type"),
    )

    # ── New table: fuel_transactions ──────────────────────────────────
    op.create_table(
        "fuel_transactions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "type",
            sa.Enum("arrival", "departure", name="transactiontype"),
            nullable=False,
        ),
        sa.Column("fuel_type", sa.String(50), nullable=False),
        sa.Column("volume", sa.Numeric(12, 2), nullable=False),
        sa.Column("transaction_date", sa.DateTime(timezone=True), nullable=False),
        # departure context
        sa.Column("trip_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("order_number", sa.String(30), nullable=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("driver_name", sa.String(255), nullable=True),
        # arrival context
        sa.Column("supplier_name", sa.String(255), nullable=True),
        sa.Column("invoice_number", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fuel_transactions_type",             "fuel_transactions", ["type"])
    op.create_index("ix_fuel_transactions_fuel_type",        "fuel_transactions", ["fuel_type"])
    op.create_index("ix_fuel_transactions_transaction_date", "fuel_transactions", ["transaction_date"])
    op.create_index("ix_fuel_transactions_trip_id",          "fuel_transactions", ["trip_id"])

    # ── New columns on trips ───────────────────────────────────────────
    op.add_column("trips", sa.Column("inv_fuel_type",    sa.String(50),  nullable=True))
    op.add_column("trips", sa.Column("inv_order_number", sa.String(30),  nullable=True))
    op.add_column("trips", sa.Column("inv_client_id",    postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("trips", sa.Column("inv_client_name",  sa.String(255), nullable=True))
    op.add_column("trips", sa.Column("inv_driver_name",  sa.String(255), nullable=True))


def downgrade() -> None:
    # Remove inv_* columns from trips
    op.drop_column("trips", "inv_driver_name")
    op.drop_column("trips", "inv_client_name")
    op.drop_column("trips", "inv_client_id")
    op.drop_column("trips", "inv_order_number")
    op.drop_column("trips", "inv_fuel_type")

    # Drop fuel tables
    op.drop_index("ix_fuel_transactions_trip_id",          table_name="fuel_transactions")
    op.drop_index("ix_fuel_transactions_transaction_date", table_name="fuel_transactions")
    op.drop_index("ix_fuel_transactions_fuel_type",        table_name="fuel_transactions")
    op.drop_index("ix_fuel_transactions_type",             table_name="fuel_transactions")
    op.drop_table("fuel_transactions")
    op.drop_table("fuel_stock")
    op.execute("DROP TYPE IF EXISTS transactiontype")
