"""Правка заказчика — переименование ДТ-Л К5 / ДТ-З К5 → ДТ – Л – К5 / ДТ – З – К5

Revision ID: 0017_fuel_label
Revises: 0016
Create Date: 2026-06-16

Идемпотентно обновляем label в каталоге топлива. Коды не трогаем — данные совместимы.
Downgrade возвращает прежние подписи.

NB: на ветке mobile отдельный 0017_idempotency_keys (offline outbox) — это
параллельная история. При будущем merge mobile→master потребуется alembic merge.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0017_fuel_label"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE fuel_types SET label = 'ДТ – Л – К5' WHERE code = 'diesel_summer'")
    op.execute("UPDATE fuel_types SET label = 'ДТ – З – К5' WHERE code = 'diesel_winter'")


def downgrade() -> None:
    op.execute("UPDATE fuel_types SET label = 'ДТ-Л К5' WHERE code = 'diesel_summer'")
    op.execute("UPDATE fuel_types SET label = 'ДТ-З К5' WHERE code = 'diesel_winter'")
