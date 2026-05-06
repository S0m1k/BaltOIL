import uuid
from datetime import datetime
from sqlalchemy import Text, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.order import OrderStatus


class OrderStatusLog(Base):
    """Полная история смены статусов заявки."""

    __tablename__ = "order_status_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(SAEnum(OrderStatus), nullable=True)
    to_status: Mapped[OrderStatus] = mapped_column(SAEnum(OrderStatus), nullable=False)

    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changed_by_role: Mapped[str | None] = mapped_column(nullable=True)

    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    order: Mapped["Order"] = relationship("Order", back_populates="status_logs")
