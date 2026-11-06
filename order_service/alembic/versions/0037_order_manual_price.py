"""Заявка помнит ручную цену за литр (staff ввёл цену — считаем по ней точно).

Revision ID: 0037_order_manual_price
Revises: 0036_tariff_formula_round_to

Раньше ручная цена использовалась только при создании заявки и нигде не
хранилась: итог округлялся через «цену за литр с доставкой» (CRM-27) и терял
копейки/рубли (77 × 900 + 4000 давало 73 296 вместо 73 300), а любой
последующий пересчёт возвращал заявку к тарифу. Теперь цена хранится, итог
такой заявки = цена × литры + доставка без округления, а счёт выводит топливо
и доставку отдельными строками. NULL — заявка по тарифу, поведение прежнее.
"""
from alembic import op

revision = "0037_order_manual_price"
down_revision = "0036_tariff_formula_round_to"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS manual_price_per_liter NUMERIC(12, 4)")


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS manual_price_per_liter")
