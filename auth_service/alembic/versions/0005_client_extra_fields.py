"""Add FNS-extra fields + billing_email to client_profiles.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-23

Деплой 2 спринта 2026-06: расширенные реквизиты из DaData (ФНС/банк)
и billing_email для отправки документов и уведомлений на отдельный адрес.

Идемпотентно: ADD COLUMN IF NOT EXISTS — миграция безопасна при повторе.
"""
from alembic import op


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


COLUMNS = [
    ("okved",             "VARCHAR(20)"),
    ("okpo",              "VARCHAR(10)"),
    ("okato",             "VARCHAR(11)"),
    ("fns_status",        "VARCHAR(30)"),
    ("director_name",     "VARCHAR(255)"),
    ("swift",             "VARCHAR(11)"),
    ("billing_email",     "VARCHAR(255)"),
    ("fns_last_sync_at",  "TIMESTAMPTZ"),
]


def upgrade() -> None:
    for name, ddl in COLUMNS:
        op.execute(
            f"ALTER TABLE client_profiles ADD COLUMN IF NOT EXISTS {name} {ddl} NULL"
        )


def downgrade() -> None:
    for name, _ in COLUMNS:
        op.execute(f"ALTER TABLE client_profiles DROP COLUMN IF EXISTS {name}")
