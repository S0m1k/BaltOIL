"""Правки 2026-07-25: отгрузка (разрешена/ждём оплату) + подтверждение комментария водителем.

Revision ID: 0023_shipment_and_comment_ack
Revises: 0022_idempotency_keys
Create Date: 2026-07-25

Идемпотентно (ADD COLUMN IF NOT EXISTS) — безопасно перезапускать.

- shipment_override: ручное перекрытие админом статуса отгрузки:
  'allow' (разрешена, даже без оплаты) | 'hold' (ждём оплату, даже если
  оплачена) | NULL (автоматика от оплаты/типа клиента).
- driver_comment_ack_at: когда водитель подтвердил, что увидел комментарий
  (клиента/менеджера); NULL при непустом комментарии — бейдж «!» водителю.
"""
from typing import Sequence, Union
from alembic import op


revision: str = "0023_shipment_comment_ack"
down_revision: Union[str, None] = "0022_idempotency_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipment_override VARCHAR(10)"
    )
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS driver_comment_ack_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS shipment_override")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS driver_comment_ack_at")
