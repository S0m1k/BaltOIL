"""Deploy 1 — Ядро заявок: статусы, нумерация, ТТН, виды заявок, поля ack/ttn

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-05

Идемпотентные изменения:
1. Пересоздаём enum orderstatus через rename-swap (идемпотентно):
   старые значения in_transit/partially_delivered/closed/rejected убираем,
   добавляем cancelled. Данные мигрируются до смены типа.
2. Создаём enum orderkind: individual/company/ttn_l.
3. Добавляем колонки orders: order_kind, ttn_number, pending_driver_ack.
4. Дропаем колонку delivery_window (и enum deliverywindow).
5. Мигрируем существующие статусы:
   in_transit → accepted, partially_delivered → accepted,
   closed → delivered, rejected → cancelled.
6. Мигрируем order_kind из временного текстового поля (все существующие — individual).
7. Создаём таблицу order_kind_counters, дропаем order_year_counters.
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Миграция данных статусов (пока тип TEXT, до смены enum) ──────────
    # Временно меняем колонку на TEXT чтобы безопасно изменить enum
    op.execute("""
        ALTER TABLE orders
            ALTER COLUMN status TYPE TEXT,
            ALTER COLUMN status SET DEFAULT 'new'
    """)
    op.execute("""
        ALTER TABLE order_status_logs
            ALTER COLUMN from_status TYPE TEXT,
            ALTER COLUMN to_status TYPE TEXT
    """)

    # Мигрируем старые значения статусов.
    # asyncpg не допускает несколько команд в одном prepared statement —
    # каждый UPDATE отдельным op.execute.
    op.execute("UPDATE orders SET status = 'accepted'  WHERE status = 'in_transit'")
    op.execute("UPDATE orders SET status = 'accepted'  WHERE status = 'partially_delivered'")
    op.execute("UPDATE orders SET status = 'delivered' WHERE status = 'closed'")
    op.execute("UPDATE orders SET status = 'cancelled' WHERE status = 'rejected'")
    op.execute("UPDATE order_status_logs SET from_status = 'accepted'  WHERE from_status = 'in_transit'")
    op.execute("UPDATE order_status_logs SET from_status = 'accepted'  WHERE from_status = 'partially_delivered'")
    op.execute("UPDATE order_status_logs SET from_status = 'delivered' WHERE from_status = 'closed'")
    op.execute("UPDATE order_status_logs SET from_status = 'cancelled' WHERE from_status = 'rejected'")
    op.execute("UPDATE order_status_logs SET to_status   = 'accepted'  WHERE to_status   = 'in_transit'")
    op.execute("UPDATE order_status_logs SET to_status   = 'accepted'  WHERE to_status   = 'partially_delivered'")
    op.execute("UPDATE order_status_logs SET to_status   = 'delivered' WHERE to_status   = 'closed'")
    op.execute("UPDATE order_status_logs SET to_status   = 'cancelled' WHERE to_status   = 'rejected'")

    # ── 2. Пересоздаём enum orderstatus ─────────────────────────────────────
    op.execute("DROP TYPE IF EXISTS orderstatus CASCADE")
    op.execute("""
        CREATE TYPE orderstatus AS ENUM ('new', 'accepted', 'delivered', 'cancelled')
    """)

    # Восстанавливаем колонки с новым enum.
    # ВАЖНО: сначала снимаем DEFAULT — Postgres не умеет авто-кастить
    # существующий TEXT-дефолт ('new') к новому enum при смене типа.
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT")
    op.execute("""
        ALTER TABLE orders
            ALTER COLUMN status TYPE orderstatus
                USING status::orderstatus,
            ALTER COLUMN status SET DEFAULT 'new'::orderstatus
    """)
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN from_status DROP DEFAULT")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN to_status DROP DEFAULT")
    op.execute("""
        ALTER TABLE order_status_logs
            ALTER COLUMN from_status TYPE orderstatus
                USING from_status::orderstatus,
            ALTER COLUMN to_status TYPE orderstatus
                USING to_status::orderstatus
    """)

    # ── 3. Enum orderkind ────────────────────────────────────────────────────
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE orderkind AS ENUM ('individual', 'company', 'ttn_l');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)

    # ── 4. Новые колонки orders ──────────────────────────────────────────────
    # order_kind (добавляем nullable, потом ставим значение, потом NOT NULL)
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS order_kind orderkind
    """)
    # Все существующие заявки — individual (тестовые данные)
    op.execute("""
        UPDATE orders SET order_kind = 'individual'::orderkind WHERE order_kind IS NULL
    """)
    op.execute("""
        ALTER TABLE orders ALTER COLUMN order_kind SET NOT NULL,
                           ALTER COLUMN order_kind SET DEFAULT 'individual'::orderkind
    """)

    # ttn_number (nullable text)
    op.execute("""
        ALTER TABLE orders ADD COLUMN IF NOT EXISTS ttn_number TEXT
    """)

    # pending_driver_ack (bool, default false)
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS pending_driver_ack BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # ── 5. Дропаем delivery_window ───────────────────────────────────────────
    # Идемпотентно: проверяем наличие колонки перед дропом
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'orders' AND column_name = 'delivery_window'
            ) THEN
                ALTER TABLE orders ALTER COLUMN delivery_window DROP DEFAULT;
                ALTER TABLE orders DROP COLUMN delivery_window;
            END IF;
        END $$
    """)
    op.execute("DROP TYPE IF EXISTS deliverywindow")

    # ── 6. Новая таблица счётчиков по виду заявки ────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_kind_counters (
            kind     VARCHAR(20) PRIMARY KEY,
            last_seq BIGINT NOT NULL DEFAULT 0
        )
    """)

    # ── 7. Дропаем старую таблицу счётчиков по году ─────────────────────────
    # CASCADE на случай если есть какие-то зависимости (вряд ли, но безопасно)
    op.execute("DROP TABLE IF EXISTS order_year_counters CASCADE")


def downgrade() -> None:
    # Восстанавливаем order_year_counters
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_year_counters (
            year     INTEGER PRIMARY KEY,
            last_seq BIGINT NOT NULL DEFAULT 0
        )
    """)

    # Восстанавливаем delivery_window
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE deliverywindow AS ENUM ('07-13', '13-16', '16-20', '20-24');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("""
        ALTER TABLE orders
            ADD COLUMN IF NOT EXISTS delivery_window deliverywindow NOT NULL DEFAULT '07-13'::deliverywindow
    """)

    op.execute("DROP TABLE IF EXISTS order_kind_counters")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS pending_driver_ack")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS ttn_number")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS order_kind")
    op.execute("DROP TYPE IF EXISTS orderkind")

    # Восстанавливаем полный orderstatus enum (без данных — только схема)
    op.execute("""
        ALTER TABLE orders ALTER COLUMN status TYPE TEXT,
                           ALTER COLUMN status SET DEFAULT 'new'
    """)
    op.execute("""
        ALTER TABLE order_status_logs
            ALTER COLUMN from_status TYPE TEXT,
            ALTER COLUMN to_status TYPE TEXT
    """)
    op.execute("DROP TYPE IF EXISTS orderstatus CASCADE")
    op.execute("""
        CREATE TYPE orderstatus AS ENUM (
            'new', 'accepted', 'in_transit', 'delivered',
            'partially_delivered', 'closed', 'rejected'
        )
    """)
    op.execute("""
        ALTER TABLE orders
            ALTER COLUMN status TYPE orderstatus USING status::orderstatus,
            ALTER COLUMN status SET DEFAULT 'new'::orderstatus
    """)
    op.execute("""
        ALTER TABLE order_status_logs
            ALTER COLUMN from_status TYPE orderstatus USING from_status::orderstatus,
            ALTER COLUMN to_status TYPE orderstatus USING to_status::orderstatus
    """)
