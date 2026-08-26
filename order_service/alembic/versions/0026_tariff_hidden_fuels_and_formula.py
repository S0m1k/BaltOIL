"""Правки CRM-33 (2026-08-26): «глазик» видов топлива + формульные тарифы.

Revision ID: 0026_tariff_hidden_fuels_and_formula
Revises: 0025_document_display_name

Аддитивно и идемпотентно:
- tariff_fuel_prices.is_hidden BOOLEAN NOT NULL DEFAULT false — скрытый вид
  топлива не требует цены и не предлагается клиенту по этому тарифу;
- tariff_fuel_prices.price_per_liter → NULL допустим (у скрытых цены может не быть);
- tariffs.base_tariff_id / formula_type / formula_value — кастомный тариф может
  считаться от базового (наценка/скидка в % или ₽/л), пересчёт при чтении.

Существующие тарифы не затрагиваются: is_hidden=false, формула NULL.
"""
from alembic import op

revision = "0026_tariff_hidden_fuels_and_formula"
down_revision = "0025_document_display_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE tariff_fuel_prices
            ADD COLUMN IF NOT EXISTS is_hidden BOOLEAN NOT NULL DEFAULT false
    """)
    op.execute("""
        ALTER TABLE tariff_fuel_prices
            ALTER COLUMN price_per_liter DROP NOT NULL
    """)
    op.execute("""
        ALTER TABLE tariffs
            ADD COLUMN IF NOT EXISTS base_tariff_id UUID NULL
                REFERENCES tariffs(id) ON DELETE SET NULL,
            ADD COLUMN IF NOT EXISTS formula_type VARCHAR(10) NULL,
            ADD COLUMN IF NOT EXISTS formula_value NUMERIC(10, 4) NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tariffs_base_tariff_id
            ON tariffs (base_tariff_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tariffs_base_tariff_id")
    op.execute("""
        ALTER TABLE tariffs
            DROP COLUMN IF EXISTS base_tariff_id,
            DROP COLUMN IF EXISTS formula_type,
            DROP COLUMN IF EXISTS formula_value
    """)
    op.execute("""
        ALTER TABLE tariff_fuel_prices
            DROP COLUMN IF EXISTS is_hidden
    """)
    # price_per_liter обратно в NOT NULL не возвращаем: могли появиться NULL-строки
