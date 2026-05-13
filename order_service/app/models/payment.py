import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Text, Numeric, DateTime, Enum as SAEnum, Boolean, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class PaymentStatus(str, enum.Enum):
    PENDING  = "pending"   # Ожидает оплаты
    PAID     = "paid"      # Оплачено
    CANCELLED = "cancelled" # Отменено


class PaymentMethod(str, enum.Enum):
    CASH          = "cash"           # Наличные
    CARD          = "card"           # Карта
    BANK_TRANSFER = "bank_transfer"  # Банковский перевод


class PaymentKind(str, enum.Enum):
    PREPAYMENT = "prepayment"  # Предоплата (по заявленному объёму)
    ACTUAL     = "actual"      # По факту доставки (по volume_delivered)
    INVOICE    = "invoice"     # Счёт (для юр. лиц)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    kind: Mapped[PaymentKind] = mapped_column(SAEnum(PaymentKind), nullable=False)
    status: Mapped[PaymentStatus] = mapped_column(
        SAEnum(PaymentStatus), nullable=False, default=PaymentStatus.PENDING, index=True
    )
    method: Mapped[PaymentMethod | None] = mapped_column(SAEnum(PaymentMethod), nullable=True)

    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)

    # Номер счёта / документа
    invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)

    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship("Order", back_populates="payments")
