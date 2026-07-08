"""Правка заказчика — обозначение топлива снова через дефис: ДТ – Л – К5 / ДТ – З – К5 → ДТ-Л-К5 / ДТ-З-К5

Revision ID: 0019_fuel_label_hyphen
Revises: 0018_client_objects
Create Date: 2026-06-24

Идемпотентно обновляем label в каталоге топлива. Коды не трогаем — данные совместимы.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0019_fuel_label_hyphen"
down_revision: Union[str, None] = "0018_client_objects"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE fuel_types SET label = 'ДТ-Л-К5' WHERE code = 'diesel_summer'")
    op.execute("UPDATE fuel_types SET label = 'ДТ-З-К5' WHERE code = 'diesel_winter'")


def downgrade() -> None:
    op.execute("UPDATE fuel_types SET label = 'ДТ – Л – К5' WHERE code = 'diesel_summer'")
    op.execute("UPDATE fuel_types SET label = 'ДТ – З – К5' WHERE code = 'diesel_winter'")
