"""Правки CRM-32 (2026-08-26): журнал изменения цен тарифов.

Revision ID: 0027_tariff_price_history
Revises: 0026_tariff_hidden_fuels_and_formula

Новая таблица tariff_price_history: кто, когда, какое топливо, было → стало.
Бэкфилла нет — история ведётся с момента деплоя.
"""
from alembic import op

revision = "0027_tariff_price_history"
down_revision = "0026_tariff_hidden_fuels_and_formula"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS tariff_price_history (
            id UUID PRIMARY KEY,
            tariff_id UUID NOT NULL REFERENCES tariffs(id) ON DELETE CASCADE,
            fuel_type VARCHAR(30) NOT NULL,
            change_kind VARCHAR(20) NOT NULL,
            old_price NUMERIC(10, 4) NULL,
            new_price NUMERIC(10, 4) NULL,
            changed_by_id UUID NULL,
            changed_by_role VARCHAR(20) NULL,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tariff_price_history_tariff_id
            ON tariff_price_history (tariff_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tariff_price_history_changed_at
            ON tariff_price_history (changed_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tariff_price_history")
