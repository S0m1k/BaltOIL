"""Add tariff_id to client_profiles

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-14

Adds a soft-FK reference to the tariffs table in order_service DB.
NULL means "use the default tariff" — order_service resolves this at runtime.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_profiles",
        sa.Column("tariff_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # No index needed — lookups are by user_id (PK), not by tariff_id


def downgrade() -> None:
    op.drop_column("client_profiles", "tariff_id")
