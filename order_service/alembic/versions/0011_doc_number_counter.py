"""Атомарный счётчик номеров документов (фикс гонки нумерации)

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-31

Изменения (идемпотентные — деплой катится на живую БД):
1. CREATE TABLE IF NOT EXISTS doc_number_counters — атомарный счётчик номеров
   документов по (префикс, год), как order_year_counters / contract_month_counters.
   Заменяет прежний COUNT(*)+1 в _next_doc_number, который под нагрузкой давал
   одинаковые doc_number → IntegrityError на flush внутри транзакции перехода статуса.
2. SEED: засеять last_seq максимальным существующим номером по каждому
   (префикс-год), иначе новые номера начнутся с 1 и столкнутся с уже выпущенными.

Партиал-уникальный индекс (order_id, doc_type) НЕ добавляем намеренно: на живой БД
уже могут быть дубли (старый баг), и создание уникального индекса упало бы. Дубли
на повторных рейсах теперь предотвращаются на уровне приложения (idempotency-guard
в generate_*). Индекс можно добавить отдельной миграцией после дедупликации.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS doc_number_counters (
            prefix_key VARCHAR(16) PRIMARY KEY,
            last_seq   INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Засеять счётчик из существующих документов: prefix_key = всё до последнего
    # "-NNNNNN", last_seq = максимальный номер в этой группе. GREATEST на конфликте,
    # чтобы повторный прогон миграции не уменьшил уже сдвинутый счётчик.
    op.execute(r"""
        INSERT INTO doc_number_counters (prefix_key, last_seq)
        SELECT substring(doc_number from '^(.+)-[0-9]+$') AS prefix_key,
               MAX(CAST(substring(doc_number from '-([0-9]+)$') AS INTEGER)) AS last_seq
        FROM documents
        WHERE doc_number ~ '^.+-[0-9]+$'
        GROUP BY 1
        ON CONFLICT (prefix_key)
        DO UPDATE SET last_seq = GREATEST(doc_number_counters.last_seq, EXCLUDED.last_seq)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS doc_number_counters")
