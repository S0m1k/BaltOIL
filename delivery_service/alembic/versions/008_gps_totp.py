"""GPS: секрет TOTP для подтверждения трекера (спринт 2026-09-19).

Revision ID: 008
Revises: 007

gps_devices.totp_secret_enc TEXT NULL — секрет, зашифрованный ключом из .env.

Идемпотентно.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE gps_devices ADD COLUMN IF NOT EXISTS totp_secret_enc TEXT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE gps_devices DROP COLUMN IF EXISTS totp_secret_enc")
