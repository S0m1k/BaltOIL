"""Перевозка (09.2026): вид заявки «transport» + детали перевозки.

Revision ID: 0032_transport_orders
Revises: 0031_transport_directory

Заявка на перевозку — обычный Order с order_kind='transport' плюс строка 1:1
в transport_details. Так перевозка бесплатно получает общий список заявок,
счётчики вкладок, статусы, номера ТТН, журнал действий и чат; двадцать пустых
у всех остальных заявок колонок в orders при этом не появляется.

ADD VALUE к enum-типу нельзя выполнять внутри транзакции в PostgreSQL < 12,
поэтому используем IF NOT EXISTS и отдельный autocommit-блок.
"""
from alembic import op

revision = "0032_transport_orders"
down_revision = "0031_transport_directory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Новое значение enum orderkind. COMMIT перед ALTER TYPE: в PostgreSQL
    # ADD VALUE не может выполняться в транзакционном блоке вместе с DDL,
    # который затем это значение использует.
    op.execute("COMMIT")
    op.execute("ALTER TYPE orderkind ADD VALUE IF NOT EXISTS 'transport'")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS transport_details (
            order_id UUID PRIMARY KEY
                REFERENCES orders (id) ON DELETE CASCADE,
            transport_type VARCHAR(20) NOT NULL,
            client_object_id UUID,

            route_from_kind VARCHAR(20),
            route_from_id UUID,
            route_from_text TEXT,
            route_to_kind VARCHAR(20),
            route_to_id UUID,
            route_to_text TEXT,
            waypoints JSONB,

            amount_kg NUMERIC(14, 3),
            amount_l NUMERIC(14, 3),
            desired_date_text TEXT,

            price_per_kg NUMERIC(14, 4),
            price_per_l NUMERIC(14, 4),
            density NUMERIC(10, 4),
            total_amount NUMERIC(14, 2),
            supplier_payments JSONB,

            delivery_price NUMERIC(14, 2),
            delivery_paid BOOLEAN NOT NULL DEFAULT FALSE,

            driver_payment_amount NUMERIC(14, 2),
            driver_payment_percent NUMERIC(6, 2),

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transport_details_client_object_id "
        "ON transport_details (client_object_id)"
    )


def downgrade() -> None:
    # Значение enum не удаляем: PostgreSQL не умеет DROP VALUE, а пересоздание
    # типа переписало бы колонку order_kind на всех заявках ради отката.
    op.execute("DROP TABLE IF EXISTS transport_details")
