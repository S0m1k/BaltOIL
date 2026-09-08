"""CRM-42 (2026-09-04): раздельная нумерация ТТН по типу контрагента.

Revision ID: 0028_ttn_kind_numbering
Revises: 0027_tariff_price_history

1. orders.ttn_kind — тип ТТН (company=Ю / individual=Ф / special=Л).
2. order_kind_counters.kind расширен до VARCHAR(40): ключи счётчиков ТТН
   теперь содержат год и вид ('ttn-2026-individual').

Бэкфилл: уже выданные номера НЕ переписываются (формат исторических номеров
остаётся 'ТТН-2026-000042'), проставляется только классификация, чтобы
фильтр отчётов по Ю/Ф видел и старые ТТН. Классифицируем по виду заявки:
individual → Ф, всё остальное (company, ttn_l) → Ю; последнее совпадает с
тем, что старый общий счётчик закреплён за Ю.

CRM-42.1: с включением префикса Л внутренние заявки (ttn_l) нумеруются как
special, но бэкфилл здесь НЕ переклассифицируем — у старых внутренних заявок
номер уже выдан из Ю-ряда, и смена ttn_kind на special порвала бы правило
«префикс в номере ↔ ttn_kind». Старые остаются Ю, новые идут по ряду Л.
"""
from alembic import op

revision = "0028_ttn_kind_numbering"
down_revision = "0027_tariff_price_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS ttn_kind VARCHAR(20)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_ttn_kind ON orders (ttn_kind)"
    )
    op.execute("""
        UPDATE orders
           SET ttn_kind = CASE
                   WHEN order_kind::text = 'individual' THEN 'individual'
                   ELSE 'company'
               END
         WHERE ttn_number IS NOT NULL
           AND ttn_kind IS NULL
    """)
    op.execute(
        "ALTER TABLE order_kind_counters ALTER COLUMN kind TYPE VARCHAR(40)"
    )


def downgrade() -> None:
    # Ключи счётчиков ТТН длиннее 20 символов удаляем — иначе сужение типа
    # упадёт. Номера заявок и ТТН в orders при этом не трогаем.
    op.execute("DELETE FROM order_kind_counters WHERE length(kind) > 20")
    op.execute(
        "ALTER TABLE order_kind_counters ALTER COLUMN kind TYPE VARCHAR(20)"
    )
    op.execute("DROP INDEX IF EXISTS ix_orders_ttn_kind")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS ttn_kind")
