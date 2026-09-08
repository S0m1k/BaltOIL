"""Правки 2026-08-24: ручное имя документа-счёта.

Revision ID: 0025_document_display_name
Revises: 0024_delivery_cost_is_manual

documents.display_name VARCHAR(120) NULL — заданное вручную отображаемое имя
(перекрывает авто-«{номер} {КраткоеИмяОрг}»). Аддитивно, идемпотентно.
"""
from alembic import op

revision = "0025_document_display_name"
down_revision = "0024_delivery_cost_is_manual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS display_name VARCHAR(120) NULL
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE documents
            DROP COLUMN IF EXISTS display_name
    """)
