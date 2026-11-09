"""Правки 2026-11-10 — комментарий менеджера и файлы организации, клиент без пароля.

Revision ID: 0014
Revises: 0013

Идемпотентно и аддитивно (CREATE/ADD ... IF NOT EXISTS), безопасно перезапускать:

  organizations.manager_comment TEXT NULL — заметка сотрудников рядом с названием
      организации (CRM-62); клиентам не отдаётся.
  organization_files — файл с реквизитами (Word/PDF/Excel), хранится в БД, чтобы
      попадать в бэкапы и не зависеть от тома контейнера (CRM-63).
  users.password_set BOOLEAN NOT NULL DEFAULT TRUE — false у аккаунта, заведённого
      сотрудником без пароля: клиент придумывает его сам при регистрации по тому
      же телефону и видит свою историю заявок (CRM-59). Разовые клиенты (is_one_off)
      тоже без пароля — помечаем их сразу.
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE organizations ADD COLUMN IF NOT EXISTS manager_comment TEXT NULL")

    op.execute("""
        CREATE TABLE IF NOT EXISTS organization_files (
            id              UUID PRIMARY KEY,
            organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            filename        VARCHAR(255) NOT NULL,
            content_type    VARCHAR(120) NOT NULL,
            size            INTEGER NOT NULL,
            content         BYTEA NOT NULL,
            uploaded_by_id  UUID NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_organization_files_org "
        "ON organization_files (organization_id)"
    )

    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_set BOOLEAN NOT NULL DEFAULT TRUE")
    op.execute("""
        UPDATE users SET password_set = FALSE
        WHERE id IN (SELECT user_id FROM client_profiles WHERE is_one_off = TRUE)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_set")
    op.execute("DROP INDEX IF EXISTS ix_organization_files_org")
    op.execute("DROP TABLE IF EXISTS organization_files")
    op.execute("ALTER TABLE organizations DROP COLUMN IF EXISTS manager_comment")
