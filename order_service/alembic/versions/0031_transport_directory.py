"""Перевозка (09.2026): справочники «Нефтебазы» и «Объекты клиентов».

Revision ID: 0031_transport_directory
Revises: 0030_client_object_contact

Отдельные таблицы, а не расширение organizations/client_objects: справочник
перевозки не участвует в заявках на топливо, и любая правка общих таблиц
задевала бы работающий поток заявок. ТЗ такой вариант прямо допускает.
"""
from alembic import op

revision = "0031_transport_directory"
down_revision = "0030_client_object_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS transport_bases (
            id UUID PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            default_delivery_cost NUMERIC(12, 2),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS transport_client_objects (
            id UUID PRIMARY KEY,
            name VARCHAR(200) NOT NULL,
            client_id UUID,
            contract_file_path TEXT,
            contract_file_name TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transport_client_objects_client_id "
        "ON transport_client_objects (client_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS transport_client_addresses (
            id UUID PRIMARY KEY,
            object_id UUID NOT NULL
                REFERENCES transport_client_objects (id) ON DELETE CASCADE,
            address TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transport_client_addresses_object_id "
        "ON transport_client_addresses (object_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transport_client_addresses")
    op.execute("DROP TABLE IF EXISTS transport_client_objects")
    op.execute("DROP TABLE IF EXISTS transport_bases")
