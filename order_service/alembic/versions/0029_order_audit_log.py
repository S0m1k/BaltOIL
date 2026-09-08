"""CRM-44 (2026-09-04): журнал действий по заявке (виден только админу).

Revision ID: 0029_order_audit_log
Revises: 0028_ttn_kind_numbering

Бэкфилла нет: журнал начинается с момента деплоя, по историческим заявкам он
пуст — это честнее, чем реконструировать «кто правил» из логов статусов.
"""
from alembic import op

revision = "0029_order_audit_log"
down_revision = "0028_ttn_kind_numbering"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS order_audit_logs (
            id          UUID PRIMARY KEY,
            order_id    UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            actor_id    UUID,
            actor_role  VARCHAR(20),
            action      VARCHAR(40) NOT NULL,
            field       VARCHAR(40),
            old_value   TEXT,
            new_value   TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_audit_logs_order_id "
        "ON order_audit_logs (order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_order_audit_logs_created_at "
        "ON order_audit_logs (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_audit_logs")
