"""Make users.email nullable (individuals may register without email).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-06

Sprint 2026-08 Deploy 6: Decision 3 — email optional for individuals.
UNIQUE constraint is kept; PostgreSQL allows multiple NULLs in a unique column.

Идемпотентно: проверяем текущую nullable-характеристику колонки перед изменением.
"""
from alembic import op
from sqlalchemy import text


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Only drop NOT NULL if the column is currently NOT NULL — idempotent.
    conn = op.get_bind()
    row = conn.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'email'"
        )
    ).fetchone()

    if row and row[0] == "NO":
        op.execute("ALTER TABLE users ALTER COLUMN email DROP NOT NULL")


def downgrade() -> None:
    # Re-add NOT NULL only if there are no NULL emails — otherwise skip to avoid crash.
    conn = op.get_bind()
    null_count = conn.execute(
        text("SELECT COUNT(*) FROM users WHERE email IS NULL")
    ).scalar()

    if null_count and null_count > 0:
        import logging
        logging.getLogger(__name__).warning(
            "0008 downgrade: %d users have NULL email — cannot restore NOT NULL constraint; skipping.",
            null_count,
        )
        return

    op.execute("ALTER TABLE users ALTER COLUMN email SET NOT NULL")
