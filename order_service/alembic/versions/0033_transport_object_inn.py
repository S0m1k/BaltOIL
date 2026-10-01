"""Перевозка: ИНН организации у объекта клиента.

Revision ID: 0033_transport_object_inn
Revises: 0032_transport_orders

Заказчик заводит «объект клиента» как организацию по ИНН с адресами в свободной
форме, а не привязывает к пользователю-физлицу.
"""
from alembic import op

revision = "0033_transport_object_inn"
down_revision = "0032_transport_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE transport_client_objects ADD COLUMN IF NOT EXISTS inn VARCHAR(12)")


def downgrade() -> None:
    op.execute("ALTER TABLE transport_client_objects DROP COLUMN IF EXISTS inn")
