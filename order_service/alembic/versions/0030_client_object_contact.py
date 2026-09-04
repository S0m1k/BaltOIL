"""CRM-45 (2026-09-04): сохранённый объект помнит организацию и контакт приёмки.

Revision ID: 0030_client_object_contact
Revises: 0029_order_audit_log

Адрес доставки уже хранился в client_objects; теперь рядом с ним живут контакт
приёмки и организация заявки — чтобы при следующей заявке на ту же организацию
и адрес, и контакт можно было выбрать, а не вводить заново.
"""
from alembic import op

revision = "0030_client_object_contact"
down_revision = "0029_order_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE client_objects ADD COLUMN IF NOT EXISTS organization_id UUID")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_objects_organization_id "
        "ON client_objects (organization_id)"
    )
    op.execute(
        "ALTER TABLE client_objects ADD COLUMN IF NOT EXISTS contact_person_name VARCHAR(120)"
    )
    op.execute(
        "ALTER TABLE client_objects ADD COLUMN IF NOT EXISTS contact_person_phone VARCHAR(20)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE client_objects DROP COLUMN IF EXISTS contact_person_phone")
    op.execute("ALTER TABLE client_objects DROP COLUMN IF EXISTS contact_person_name")
    op.execute("DROP INDEX IF EXISTS ix_client_objects_organization_id")
    op.execute("ALTER TABLE client_objects DROP COLUMN IF EXISTS organization_id")
