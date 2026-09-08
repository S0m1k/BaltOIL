"""Правки 2026-08-24: флаг «стоимость доставки задана вручную».

Revision ID: 0024_delivery_cost_is_manual
Revises: 0023_shipment_comment_ack
Create Date: 2026-08-24

Идемпотентно (ADD COLUMN IF NOT EXISTS) — безопасно перезапускать.

delivery_cost_is_manual: TRUE, если стоимость доставки ввёл человек (админ в
форме создания или карандашиком в карточке). Пересчёт итога при смене
объёма/топлива такую доставку не перетирает зональной.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0024_delivery_cost_is_manual"
down_revision: Union[str, None] = "0023_shipment_comment_ack"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS "
        "delivery_cost_is_manual BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS delivery_cost_is_manual")
