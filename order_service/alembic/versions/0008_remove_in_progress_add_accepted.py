"""Remove IN_PROGRESS, add ACCEPTED to orderstatus

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-28

Business: убираем статус IN_PROGRESS — менеджер больше не «берёт в работу»,
водитель сам принимает заявку (NEW → ACCEPTED), потом сам выезжает
(ACCEPTED → IN_TRANSIT). Это закрывает баг, когда менеджер случайно
жал «В работе» и водитель потом не мог принять.

Стратегия:
  1. Добавляем 'accepted' в существующий enum (ALTER TYPE ADD VALUE).
  2. Мигрируем существующие заявки in_progress → accepted (сохраняет
     то, что водитель уже был назначен; если driver_id null — тоже
     ничего страшного, статус допустим без driver_id и менеджер сам
     отклонит/закроет).
  3. Пересоздаём enum без in_progress — rename → create → alter →
     drop. Те же приёмы что в 0005. DROP DEFAULT перед сменой типа
     (иначе postgres не кастит дефолт автоматически).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавляем 'accepted' в enum (idempotent через guard)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'accepted'
                  AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'orderstatus')
            ) THEN
                ALTER TYPE orderstatus ADD VALUE 'accepted';
            END IF;
        END $$;
    """)
    # ALTER TYPE ADD VALUE требует отдельной транзакции прежде чем новое
    # значение можно использовать — фиксируем DDL.
    op.execute("COMMIT")
    op.execute("BEGIN")

    # 2. Мигрируем строки in_progress → accepted
    op.execute("UPDATE orders SET status = 'accepted' WHERE status = 'in_progress'")
    op.execute("UPDATE order_status_logs SET from_status = 'accepted' WHERE from_status = 'in_progress'")
    op.execute("UPDATE order_status_logs SET to_status = 'accepted' WHERE to_status = 'in_progress'")

    # 3. Пересоздаём enum без in_progress.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus')
               AND NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus_old')
            THEN
                ALTER TYPE orderstatus RENAME TO orderstatus_old;
            END IF;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderstatus') THEN
                CREATE TYPE orderstatus AS ENUM (
                    'new', 'accepted', 'in_transit',
                    'delivered', 'partially_delivered',
                    'closed', 'rejected'
                );
            END IF;
        END $$;
    """)
    # Сначала сбрасываем DEFAULT — он типизирован orderstatus_old и не
    # кастится автоматически в новый orderstatus.
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT;")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING status::text::orderstatus;")
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'new';")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN from_status TYPE orderstatus USING from_status::text::orderstatus;")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN to_status TYPE orderstatus USING to_status::text::orderstatus;")
    op.execute("DROP TYPE IF EXISTS orderstatus_old;")


def downgrade() -> None:
    # Возвращаем in_progress, конвертируем accepted → in_progress.
    op.execute("ALTER TYPE orderstatus RENAME TO orderstatus_old;")
    op.execute("""
        CREATE TYPE orderstatus AS ENUM (
            'new', 'in_progress', 'in_transit',
            'delivered', 'partially_delivered',
            'closed', 'rejected'
        );
    """)
    op.execute("UPDATE orders SET status = 'in_progress' WHERE status::text = 'accepted';")
    op.execute("UPDATE order_status_logs SET from_status = 'in_progress' WHERE from_status::text = 'accepted';")
    op.execute("UPDATE order_status_logs SET to_status = 'in_progress' WHERE to_status::text = 'accepted';")
    op.execute("ALTER TABLE orders ALTER COLUMN status DROP DEFAULT;")
    op.execute("ALTER TABLE orders ALTER COLUMN status TYPE orderstatus USING status::text::orderstatus;")
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'new';")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN from_status TYPE orderstatus USING from_status::text::orderstatus;")
    op.execute("ALTER TABLE order_status_logs ALTER COLUMN to_status TYPE orderstatus USING to_status::text::orderstatus;")
    op.execute("DROP TYPE IF EXISTS orderstatus_old;")
