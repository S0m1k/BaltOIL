"""Order.organization_id — заявка от имени организации (юрлица).

Revision ID: 0018_org_id
Revises: 0017_fuel_label
Create Date: 2026-06-17

Колонка nullable. NULL = заявка «как физлицо» или legacy-заявка до внедрения
организаций. Backfill не делаем: organizations живут в auth_service БД
(межсервисный, JOIN невозможен), исторические документы уже со снимком.
Soft FK на organizations.id — FK не создаём (разные БД).
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_org_id"
down_revision: Union[str, None] = "0017_fuel_label"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_orders_organization_id", "orders", ["organization_id"])

    # Договор — теперь на организацию (юрлицо). NULL = legacy-договор на клиента.
    op.add_column(
        "contracts",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_contracts_organization_id", "contracts", ["organization_id"])


def downgrade() -> None:
    op.drop_index("ix_contracts_organization_id", table_name="contracts")
    op.drop_column("contracts", "organization_id")
    op.drop_index("ix_orders_organization_id", table_name="orders")
    op.drop_column("orders", "organization_id")
