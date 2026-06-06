"""Deploy 3 — Таблица зон доставки

Revision ID: 003
Revises: 002
Create Date: 2026-06-06

Идемпотентная миграция: CREATE TABLE IF NOT EXISTS через DO-блок.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS delivery_zones (
            id               UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
            name             VARCHAR(120) NOT NULL,
            polygon          JSONB        NOT NULL,
            cost_coefficient NUMERIC(6,3) NOT NULL DEFAULT 1.0,
            is_active        BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS delivery_zones")
