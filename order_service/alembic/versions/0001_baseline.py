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
        ("fueltype", ["diesel_summer", "diesel_winter", "petrol_92", "petrol_95", "fuel_oil"]),
        ("orderstatus", ["new", "in_progress", "assigned", "in_transit", "delivered", "partially_delivered", "closed", "rejected"]),
        ("paymenttype", ["invoice", "on_delivery"]),
        ("orderpriority", ["normal", "urgent"]),
        ("paymentstatus", ["pending", "paid", "cancelled"]),
        ("paymentmethod", ["cash", "card", "bank_transfer"]),
        ("paymentkind", ["prepayment", "actual", "invoice"]),
    ]:
        postgresql.ENUM(*values, name=name, create_type=True).create(op.get_bind(), checkfirst=True)

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_number", sa.String(30), nullable=False, unique=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fuel_type", sa.Enum("diesel_summer", "diesel_winter", "petrol_92", "petrol_95", "fuel_oil", name="fueltype"), nullable=False),
        sa.Column("volume_requested", sa.Numeric(10, 2), nullable=False),
        sa.Column("volume_delivered", sa.Numeric(10, 2), nullable=True),
        sa.Column("delivery_address", sa.Text(), nullable=False),
        sa.Column("desired_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_type", sa.Enum("invoice", "on_delivery", name="paymenttype"), nullable=False, server_default="invoice"),
        sa.Column("status", sa.Enum("new", "in_progress", "assigned", "in_transit", "delivered", "partially_delivered", "closed", "rejected", name="orderstatus"), nullable=False, server_default="new"),
        sa.Column("priority", sa.Enum("normal", "urgent", name="orderpriority"), nullable=False, server_default="normal"),
        sa.Column("manager_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("driver_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("client_comment", sa.Text(), nullable=True),
        sa.Column("manager_comment", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("payment_status", sa.String(20), nullable=False, server_default="unpaid"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_orders_order_number", "orders", ["order_number"], unique=True)
    op.create_index("ix_orders_client_id", "orders", ["client_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_driver_id", "orders", ["driver_id"])
    op.create_index("ix_orders_payment_status", "orders", ["payment_status"])

    op.create_table(
        "order_status_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.Enum("new", "in_progress", "assigned", "in_transit", "delivered", "partially_delivered", "closed", "rejected", name="orderstatus"), nullable=True),
        sa.Column("to_status", sa.Enum("new", "in_progress", "assigned", "in_transit", "delivered", "partially_delivered", "closed", "rejected", name="orderstatus"), nullable=False),
        sa.Column("changed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_by_role", sa.String(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_order_status_logs_order_id", "order_status_logs", ["order_id"])
    op.create_index("ix_order_status_logs_created_at", "order_status_logs", ["created_at"])

    op.create_table(
        "order_year_counters",
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("last_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Enum("prepayment", "actual", "invoice", name="paymentkind"), nullable=False),
        sa.Column("status", sa.Enum("pending", "paid", "cancelled", name="paymentstatus"), nullable=False, server_default="pending"),
        sa.Column("method", sa.Enum("cash", "card", "bank_transfer", name="paymentmethod"), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=True, unique=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_index("ix_payments_client_id", "payments", ["client_id"])
    op.create_index("ix_payments_status", "payments", ["status"])


def downgrade() -> None:
    op.drop_table("payments")
    op.drop_table("order_year_counters")
    op.drop_table("order_status_logs")
    op.drop_table("orders")
    for name in ["paymentkind", "paymentmethod", "paymentstatus", "orderpriority", "paymenttype", "orderstatus", "fueltype"]:
        op.execute(f"DROP TYPE IF EXISTS {name}")
