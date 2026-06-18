"""Сохранённые объекты доставки клиента (client_objects)

Revision ID: 0018_client_objects
Revises: 0017_fuel_label
Create Date: 2026-06-18

Идемпотентные изменения:
1. Создать таблицу client_objects (IF NOT EXISTS).
2. Создать индекс по client_id (IF NOT EXISTS).
3. Создать уникальный индекс по (client_id, delivery_address) (IF NOT EXISTS).

Downgrade: дропает таблицу (CASCADE).
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0018_client_objects"
down_revision: Union[str, None] = "0017_fuel_label"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Таблица client_objects ─────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS client_objects (
            id               UUID         NOT NULL DEFAULT gen_random_uuid(),
            client_id        UUID         NOT NULL,
            name             VARCHAR(120),
            delivery_address TEXT         NOT NULL,
            delivery_lat     NUMERIC(10,7),
            delivery_lon     NUMERIC(10,7),
            created_by_id    UUID,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)

    # ── 2. Индекс по client_id ────────────────────────────────────────────────
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_client_objects_client_id
            ON client_objects (client_id)
    """)

    # ── 3. Уникальный индекс (client_id, delivery_address) ───────────────────
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_client_object_addr
            ON client_objects (client_id, delivery_address)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_objects CASCADE")
