"""Каталог топлива: ДТ-Е-К5 делится на сорт F и сорт C.

Revision ID: 0035_dt_e_grades
Revises: 0034_transport_address_name

Существующий вид «ДТ-Е-К5» (в проде заведён админом через каталог) переименовывается
в «ДТ-Е-К5, сорт F» — код и все заявки/тарифы/остатки на нём сохраняются.
Добавляется новый вид «ДТ-Е-К5, сорт С» (код dt_e_c) сразу после него.
Идемпотентно: повторный прогон ничего не ломает.
"""
from alembic import op

revision = "0035_dt_e_grades"
down_revision = "0034_transport_address_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE fuel_types
           SET label = 'ДТ-Е-К5, сорт F'
         WHERE code <> 'dt_e_c'
           AND label ~* '^ДТ[ –-]*Е[ –-]*К5\\s*$'
    """)
    op.execute("""
        INSERT INTO fuel_types (code, label, is_winter, sort_order, is_active)
        SELECT 'dt_e_c', 'ДТ-Е-К5, сорт С', COALESCE(f.is_winter, TRUE),
               COALESCE(f.sort_order, 2), TRUE
          FROM (SELECT 1) AS one
          LEFT JOIN fuel_types f ON f.label = 'ДТ-Е-К5, сорт F'
        ON CONFLICT (code) DO UPDATE SET label = EXCLUDED.label
    """)


def downgrade() -> None:
    op.execute("DELETE FROM fuel_types WHERE code = 'dt_e_c'")
    op.execute("UPDATE fuel_types SET label = 'ДТ-Е-К5' WHERE label = 'ДТ-Е-К5, сорт F'")
