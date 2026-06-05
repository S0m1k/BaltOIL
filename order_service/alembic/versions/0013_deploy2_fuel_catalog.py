"""Deploy 2 — Каталог топлива: таблица fuel_types, seed, конвертация orders.fuel_type

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-05

Идемпотентные изменения:
1. Создаём таблицу fuel_types (IF NOT EXISTS).
2. Seed 5 строк — INSERT ON CONFLICT DO UPDATE (повторный прогон обновляет label).
3. Конвертируем orders.fuel_type: fueltype enum → VARCHAR.
4. Дропаем тип fueltype (IF EXISTS).

Downgrade:
- Воссоздаём enum fueltype, конвертируем обратно.
- Дропаем таблицу fuel_types.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Создать таблицу fuel_types ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS fuel_types (
            code        VARCHAR(50)  PRIMARY KEY,
            label       VARCHAR(100) NOT NULL,
            is_winter   BOOLEAN      NOT NULL DEFAULT FALSE,
            sort_order  INTEGER      NOT NULL DEFAULT 0,
            is_active   BOOLEAN      NOT NULL DEFAULT TRUE
        )
    """)

    # ── 2. Seed 5 строк (ON CONFLICT обновляет label при повторном прогоне) ───
    op.execute("""
        INSERT INTO fuel_types (code, label, is_winter, sort_order, is_active) VALUES
            ('diesel_summer', 'ДТ-Л К5',  FALSE, 1, TRUE),
            ('diesel_winter', 'ДТ-З К5',  TRUE,  2, TRUE),
            ('petrol_92',     'АИ-92',     FALSE, 3, TRUE),
            ('petrol_95',     'АИ-95',     FALSE, 4, TRUE),
            ('fuel_oil',      'М-100',     FALSE, 5, TRUE)
        ON CONFLICT (code) DO UPDATE
            SET label = EXCLUDED.label,
                sort_order = EXCLUDED.sort_order
    """)

    # ── 3. Конвертировать orders.fuel_type: fueltype enum → VARCHAR ───────────
    # Проверяем, является ли столбец уже VARCHAR (идемпотентность при повторном прогоне)
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'orders'
                  AND column_name = 'fuel_type'
                  AND udt_name = 'fueltype'
            ) THEN
                ALTER TABLE orders
                    ALTER COLUMN fuel_type TYPE VARCHAR(50)
                    USING fuel_type::text;
            END IF;
        END$$
    """)

    # ── 4. Дропаем тип fueltype (IF EXISTS) ──────────────────────────────────
    op.execute("DROP TYPE IF EXISTS fueltype")


def downgrade() -> None:
    # Воссоздаём enum fueltype
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'fueltype') THEN
                CREATE TYPE fueltype AS ENUM (
                    'diesel_summer', 'diesel_winter',
                    'petrol_92', 'petrol_95', 'fuel_oil'
                );
            END IF;
        END$$
    """)

    # Конвертируем orders.fuel_type обратно в enum
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'orders'
                  AND column_name = 'fuel_type'
                  AND udt_name = 'varchar'
            ) THEN
                ALTER TABLE orders
                    ALTER COLUMN fuel_type TYPE fueltype
                    USING fuel_type::fueltype;
            END IF;
        END$$
    """)

    # Дропаем таблицу (seed-данные при downgrade НЕ удаляются из истории,
    # но таблица уходит — исторически приемлемо, т.к. при upg-downgrade перед продом)
    op.execute("DROP TABLE IF EXISTS fuel_types")
