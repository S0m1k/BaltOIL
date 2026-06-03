"""Make users.email nullable (физлицо регистрируется по телефону, email — позже в ЛК).

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-03

Спринт 2026-06: регистрация физлиц по номеру телефона + паролю. email опционален
и заполняется позже в личном кабинете. Уникальный индекс остаётся — Postgres
допускает несколько NULL в unique-индексе.

Идемпотентно: DROP NOT NULL безопасно повторять.
"""
from alembic import op


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN email DROP NOT NULL")


def downgrade() -> None:
    # Откат невозможен, если есть пользователи без email — оставляем безопасным no-op
    # с попыткой вернуть NOT NULL только когда NULL'ов нет.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM users WHERE email IS NULL) THEN
                ALTER TABLE users ALTER COLUMN email SET NOT NULL;
            END IF;
        END $$;
        """
    )
