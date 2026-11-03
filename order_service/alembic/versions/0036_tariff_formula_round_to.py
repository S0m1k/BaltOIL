"""Формульный тариф: округление результата до шага (₽).

Revision ID: 0036_tariff_formula_round_to
Revises: 0035_dt_e_grades

Нужно для «базовый для физлиц = базовый юрлиц −10% с округлением до 50 копеек».
NULL — без округления, поведение существующих тарифов не меняется.
"""
from alembic import op

revision = "0036_tariff_formula_round_to"
down_revision = "0035_dt_e_grades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tariffs ADD COLUMN IF NOT EXISTS formula_round_to NUMERIC(6, 2)")


def downgrade() -> None:
    op.execute("ALTER TABLE tariffs DROP COLUMN IF EXISTS formula_round_to")
