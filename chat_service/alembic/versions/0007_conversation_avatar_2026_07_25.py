"""Правки 2026-07-25: аватарка чата (картинка группы).

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-25

Идемпотентно (ADD COLUMN IF NOT EXISTS) — безопасно перезапускать.
avatar_path — имя файла в media/chat/{conv_id}/ (uuid.ext), как у вложений.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS avatar_path VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS avatar_path")
