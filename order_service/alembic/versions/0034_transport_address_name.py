"""Перевозка: название объекта у адреса организации.

Revision ID: 0034_transport_address_name
Revises: 0033_transport_object_inn

Организация-клиент имеет несколько объектов: у каждого своё название и адрес
в свободной форме.
"""
from alembic import op

revision = "0034_transport_address_name"
down_revision = "0033_transport_object_inn"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transport_client_addresses ADD COLUMN IF NOT EXISTS name VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE transport_client_addresses DROP COLUMN IF EXISTS name")
