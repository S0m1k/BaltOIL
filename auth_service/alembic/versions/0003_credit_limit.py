"""Add credit_limit to client_profiles

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-20

Adds credit_limit NUMERIC(12,2) NULL to client_profiles.
NULL = no credit limit (orders cannot be closed in debt without manager override).
Non-null value = maximum amount that can be closed as debt automatically.
"""

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "client_profiles",
        sa.Column("credit_limit", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("client_profiles", "credit_limit")
