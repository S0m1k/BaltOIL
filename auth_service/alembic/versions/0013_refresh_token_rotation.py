"""Правки 2026-08-24 — grace-окно при параллельной ротации refresh-токенов.

Revision ID: 0013
Revises: 0012

Идемпотентно и аддитивно (без backfill, без блокирующих операций):
  refresh_tokens.revoked_at    TIMESTAMPTZ NULL — когда токен был отозван;
  refresh_tokens.rotated_to_id UUID NULL        — id токена-преемника.

Пара (revoked_at, rotated_to_id) отличает штатную ротацию от logout/кражи:
при ротации проставляются оба поля, при logout/logout_all — только revoked_at.
FK на refresh_tokens.id намеренно НЕ ставим: столбец добавляется на живой
проде, а FK потребовал бы валидации/блокировки и мешал бы очистке старых строк.
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE refresh_tokens
            ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ NULL
    """)
    op.execute("""
        ALTER TABLE refresh_tokens
            ADD COLUMN IF NOT EXISTS rotated_to_id UUID NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE refresh_tokens
            DROP COLUMN IF EXISTS rotated_to_id
    """)
    op.execute("""
        ALTER TABLE refresh_tokens
            DROP COLUMN IF EXISTS revoked_at
    """)
