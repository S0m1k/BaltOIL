"""Сквозная 4-значная нумерация счетов (правки 2026-06-24)

Revision ID: 0020_invoice_seq
Revises: 0019_fuel_label_hyphen
Create Date: 2026-06-24

Заказчик хочет, чтобы новые счета нумеровались просто "0145", "0146"... (без
префикса INV- и без года), причём следующий выпущенный счёт должен быть 0145.
Само переключение схемы нумерации сделано в коде (_next_doc_number,
document_service.py) — там счета (invoice/invoice_preliminary/invoice_final)
теперь берут sequence из счётчика с prefix_key="INV" (общий, без года) и
форматируют как {seq:04d}.

Эта миграция только засеивает строку счётчика doc_number_counters с
prefix_key="INV", last_seq=144, чтобы следующий nextval дал 145 → "0145".
Уже выпущенные документы (старые "INV-2026-000069" и т.п.) не трогаем —
они продолжают использовать свои старые номера, ничего не пересчитываем.

ON CONFLICT DO NOTHING — идемпотентно, повторный прогон/повторный деплой
не откатит счётчик назад, если к моменту повторного запуска уже что-то
выпущено по новой схеме.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0020_invoice_seq"
down_revision: Union[str, None] = "0019_fuel_label_hyphen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO doc_number_counters (prefix_key, last_seq)
        VALUES ('INV', 144)
        ON CONFLICT (prefix_key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM doc_number_counters WHERE prefix_key = 'INV' AND last_seq = 144
    """)
