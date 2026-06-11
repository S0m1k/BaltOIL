"""Правки 2026-06-11 — фиксированная стоимость доставки по зоне в рублях.

Revision ID: 004
Revises: 003
Create Date: 2026-06-11

Идемпотентно: delivery_zones.delivery_price NUMERIC(12,2) NULL.
NULL = legacy-режим (коэффициент × ставка тарифа за литр).
"""
from typing import Sequence, Union
from alembic import op


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE delivery_zones
            ADD COLUMN IF NOT EXISTS delivery_price NUMERIC(12,2)
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE delivery_zones
            DROP COLUMN IF EXISTS delivery_price
    """)
