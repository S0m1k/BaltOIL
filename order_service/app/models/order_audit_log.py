import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class OrderAuditLog(Base):
    """CRM-44: журнал действий по заявке — кто и что сделал.

    Отдельная таблица, а не order_status_logs: там хранится жизненный цикл
    статусов (его видят все участники заявки), а здесь — поимённая история
    правок, которую показываем ТОЛЬКО администратору.
    """

    __tablename__ = "order_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Кто: id и роль на момент действия (роль могла поменяться позже).
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Что: order_created | field_changed | status_changed |
    #      payment_recorded | payment_cancelled
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    # Для field_changed — ключ поля заявки (volume_requested, delivery_address…)
    field: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Значения храним строками: журнал читается человеком, а не пересчитывается.
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
