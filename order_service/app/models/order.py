import uuid
import enum
from datetime import datetime
from sqlalchemy import (
    String, Text, Numeric, DateTime, Enum as SAEnum,
    Integer, Boolean, func
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class FuelType(str, enum.Enum):
    DIESEL_SUMMER = "diesel_summer"   # Дизельное топливо летнее (ДТ-Л)
    DIESEL_WINTER = "diesel_winter"   # Дизельное топливо зимнее (ДТ-З)
    PETROL_92 = "petrol_92"           # Бензин АИ-92
    PETROL_95 = "petrol_95"           # Бензин АИ-95
    FUEL_OIL = "fuel_oil"             # Топочный мазут М-100


class OrderStatus(str, enum.Enum):
    NEW = "new"                                   # Новая
    IN_PROGRESS = "in_progress"                   # В работе (менеджер принял)
    IN_TRANSIT = "in_transit"                     # В рейсе (водитель взял и выехал)
    DELIVERED = "delivered"                       # Доставлена
    PARTIALLY_DELIVERED = "partially_delivered"   # Частично доставлена
    CLOSED = "closed"                             # Закрыта
    REJECTED = "rejected"                         # Отклонена


class PaymentType(str, enum.Enum):
    INVOICE = "invoice"         # По счёту (для юридических лиц)
    ON_DELIVERY = "on_delivery" # По факту, при прибытии (для физических лиц)


class OrderPriority(str, enum.Enum):
    NORMAL = "normal"
    URGENT = "urgent"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable номер: ORD-2026-000001
    order_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    # Кто создал
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Топливо
    fuel_type: Mapped[FuelType] = mapped_column(SAEnum(FuelType), nullable=False)
    volume_requested: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # литры
    volume_delivered: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)  # факт

    # Доставка
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    desired_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Оплата
    payment_type: Mapped[PaymentType] = mapped_column(
        SAEnum(PaymentType), nullable=False, default=PaymentType.PREPAID
    )

    # Статус и приоритет
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus), nullable=False, default=OrderStatus.NEW, index=True
    )
    priority: Mapped[OrderPriority] = mapped_column(
        SAEnum(OrderPriority), nullable=False, default=OrderPriority.NORMAL
    )

    # Кто обрабатывает
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Комментарии
    client_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Статус оплаты (отдельно от статуса заявки)
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unpaid", index=True
    )  # unpaid | paid | partially_paid

    # Мягкое удаление
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    status_logs: Mapped[list["OrderStatusLog"]] = relationship(
        "OrderStatusLog", back_populates="order",
        order_by="OrderStatusLog.created_at",
        cascade="all, delete-orphan",
    )
