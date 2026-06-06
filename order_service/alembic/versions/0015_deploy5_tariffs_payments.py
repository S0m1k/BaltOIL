"""Deploy 5 — Тарифы по типу клиента + долговые заявки

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-06

Идемпотентные изменения:
1. tariffs.client_type VARCHAR(20) NULL + индекс
2. orders.allow_delivery_unpaid BOOLEAN NOT NULL DEFAULT false
3. Seed: базовый тариф помечается client_type='individual';
   создаётся тариф 'Базовый (юрлица)' с client_type='company'
   (только если его нет).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. tariffs.client_type ────────────────────────────────────────────
    op.execute("""
        ALTER TABLE tariffs
            ADD COLUMN IF NOT EXISTS client_type VARCHAR(20)
    """)

    # Create index only if it doesn't exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'tariffs' AND indexname = 'ix_tariffs_client_type'
            ) THEN
                CREATE INDEX ix_tariffs_client_type ON tariffs (client_type);
            END IF;
        END$$
    """)

    # ── 2. orders.allow_delivery_unpaid ───────────────────────────────────
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS allow_delivery_unpaid BOOLEAN NOT NULL DEFAULT false
    """)

    # ── 3. Seed — помечаем индивидуальный тариф и создаём корпоративный ──
    #
    # Шаг 3a: помечаем существующий дефолтный тариф как individual
    # (если у него ещё нет client_type)
    op.execute(sa.text("""
        UPDATE tariffs
        SET client_type = 'individual'
        WHERE is_default = true
          AND is_archived = false
          AND client_type IS NULL
    """))

    # Шаг 3b: создаём дефолтный корпоративный тариф, если его нет
    op.execute(sa.text("""
        DO $$
        DECLARE
            ind_id   UUID;
            comp_id  UUID;
        BEGIN
            -- Проверяем — нет ли уже корпоративного дефолтного тарифа
            IF NOT EXISTS (
                SELECT 1 FROM tariffs
                WHERE is_default = true AND client_type = 'company'
            ) THEN
                -- Берём id индивидуального дефолтного тарифа
                SELECT id INTO ind_id FROM tariffs
                WHERE is_default = true AND client_type = 'individual'
                LIMIT 1;

                IF ind_id IS NOT NULL THEN
                    comp_id := gen_random_uuid();
                    INSERT INTO tariffs (id, name, is_default, client_type,
                                        description, is_archived, created_at, updated_at)
                    VALUES (comp_id,
                            'Базовый (юрлица)',
                            true,
                            'company',
                            'Базовый тариф для юридических лиц. Цены обновляются менеджером.',
                            false,
                            now(),
                            now());

                    -- Копируем цены на топливо из индивидуального тарифа
                    INSERT INTO tariff_fuel_prices (id, tariff_id, fuel_type, price_per_liter)
                    SELECT gen_random_uuid(), comp_id, fuel_type, price_per_liter
                    FROM tariff_fuel_prices
                    WHERE tariff_id = ind_id;
                END IF;
            END IF;
        END$$
    """))


def downgrade() -> None:
    # ── Удаляем корпоративный дефолтный тариф (cascade удалит fuel_prices) ──
    op.execute(sa.text("""
        DELETE FROM tariffs
        WHERE is_default = true AND client_type = 'company'
    """))

    # ── Сбрасываем client_type у индивидуального тарифа ──────────────────
    op.execute(sa.text("""
        UPDATE tariffs SET client_type = NULL
        WHERE is_default = true AND client_type = 'individual'
    """))

    # ── Удаляем колонки (в обратном порядке) ─────────────────────────────
    op.execute("""
        ALTER TABLE orders
            DROP COLUMN IF EXISTS allow_delivery_unpaid
    """)

    op.execute("""
        DROP INDEX IF EXISTS ix_tariffs_client_type
    """)

    op.execute("""
        ALTER TABLE tariffs
            DROP COLUMN IF EXISTS client_type
    """)
