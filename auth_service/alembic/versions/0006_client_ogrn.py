"""Add ogrn to client_profiles.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-25

Hot-fix к Deploy 2 спринта 2026-06: DaData возвращает ogrn, но колонки
в client_profiles не было — данные терялись. Добавляем колонку отдельно,
backfill пройдёт через `POST /users/{id}/fns-resync` (вручную из админки)
или при следующей регистрации/обновлении.

Идемпотентно: ADD COLUMN IF NOT EXISTS.
"""
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE client_profiles ADD COLUMN IF NOT EXISTS ogrn VARCHAR(15) NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE client_profiles DROP COLUMN IF EXISTS ogrn")
