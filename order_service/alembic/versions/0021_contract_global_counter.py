"""Сквозная (не помесячная) нумерация договоров (правка 2026-06-24)

Revision ID: 0021_contract_global_counter
Revises: 0020_invoice_seq
Create Date: 2026-06-24

Заказчик подтвердил: порядковый номер договора НЕ сбрасывается каждый месяц
(057/05 → 058/06 → 059/07) — /MM — это просто месяц подписания. Переключение
схемы нумерации сделано в коде (_next_contract_number, contract_service.py):
вместо ключа "YYYY-MM" теперь используется единый фиксированный ключ "GLOBAL"
в той же таблице contract_month_counters.

Эта миграция только засеивает строку счётчика с month_key="GLOBAL",
last_seq=57, чтобы следующий выпущенный договор получил номер 058.
Уже выпущенные договоры не трогаем — старые номера не пересчитываются.

ON CONFLICT DO NOTHING — идемпотентно, повторный прогон/повторный деплой
не откатит счётчик назад, если к моменту повторного запуска уже что-то
выпущено по новой схеме.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0021_contract_global_counter"
down_revision: Union[str, None] = "0020_invoice_seq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO contract_month_counters (month_key, last_seq)
        VALUES ('GLOBAL', 57)
        ON CONFLICT (month_key) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM contract_month_counters WHERE month_key = 'GLOBAL' AND last_seq = 57
    """)
