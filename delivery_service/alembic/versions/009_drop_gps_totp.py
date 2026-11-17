"""GPS: убрать TOTP трекеров (17.11.2026).

Revision ID: 009
Revises: 008

TOTP (миграция 008) убран по решению заказчика: трекер шлёт
«<номер> <широта> <долгота> <спутники>» без кода. Колонка
gps_devices.totp_secret_enc больше не нужна. На момент удаления ни одному
трекеру на проде секрет выдан не был — данных не теряем.

Откат возвращает пустую колонку; выданные когда-то секреты не восстановить
(их и не было), а код TOTP в приложении для этого тоже пришлось бы вернуть.

Идемпотентно.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE gps_devices DROP COLUMN IF EXISTS totp_secret_enc")


def downgrade() -> None:
    op.execute("ALTER TABLE gps_devices ADD COLUMN IF NOT EXISTS totp_secret_enc TEXT NULL")
