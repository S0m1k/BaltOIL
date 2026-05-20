"""Add client_number sequence to client_profiles.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create dedicated sequence for client numbers
    op.execute("CREATE SEQUENCE IF NOT EXISTS client_number_seq START 1")

    # Add column as nullable first so ADD COLUMN succeeds on existing rows
    op.add_column(
        "client_profiles",
        sa.Column("client_number", sa.Integer, nullable=True),
    )

    # Backfill existing profiles ordered by created_at (so older clients get lower numbers)
    op.execute("""
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) AS rn
            FROM client_profiles
        )
        UPDATE client_profiles
        SET client_number = ordered.rn
        FROM ordered
        WHERE client_profiles.id = ordered.id
    """)

    # Advance sequence past any backfilled values so next INSERT gets a fresh number
    op.execute(
        "SELECT setval('client_number_seq', "
        "COALESCE((SELECT MAX(client_number) FROM client_profiles), 0) + 1)"
    )

    # Set default so new inserts get the next sequence value automatically
    op.execute(
        "ALTER TABLE client_profiles "
        "ALTER COLUMN client_number SET DEFAULT nextval('client_number_seq')"
    )

    # Enforce NOT NULL now that every row has a value
    op.alter_column("client_profiles", "client_number", nullable=False)

    # Unique constraint (index is implicit from unique=True in the model, but be explicit)
    op.create_unique_constraint(
        "uq_client_profiles_client_number", "client_profiles", ["client_number"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_client_profiles_client_number", "client_profiles", type_="unique")
    op.drop_column("client_profiles", "client_number")
    op.execute("DROP SEQUENCE IF EXISTS client_number_seq")
