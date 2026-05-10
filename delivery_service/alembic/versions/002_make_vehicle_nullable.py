"""Make vehicle_id nullable in trips (auto-created trips don't require vehicle)

Revision ID: 002
Revises: 001
Create Date: 2026-05-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the FK constraint before altering the column
    op.drop_constraint("trips_vehicle_id_fkey", "trips", type_="foreignkey")
    # Make nullable
    op.alter_column("trips", "vehicle_id", nullable=True)
    # Re-add FK without RESTRICT (set to SET NULL on vehicle delete)
    op.create_foreign_key(
        "trips_vehicle_id_fkey",
        "trips", "vehicles",
        ["vehicle_id"], ["id"],
        ondelete="SET NULL",
    )
    # Make delivery_address nullable (auto-created trips inherit from order)
    op.alter_column("trips", "delivery_address", nullable=True)


def downgrade() -> None:
    op.alter_column("trips", "delivery_address", nullable=False)
    op.drop_constraint("trips_vehicle_id_fkey", "trips", type_="foreignkey")
    op.alter_column("trips", "vehicle_id", nullable=False)
    op.create_foreign_key(
        "trips_vehicle_id_fkey",
        "trips", "vehicles",
        ["vehicle_id"], ["id"],
        ondelete="RESTRICT",
    )
