import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Numeric, Boolean, DateTime, Text, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class TripStatus(str, enum.Enum):
    PLANNED   = "planned"     # Создан, ещё не выехал
    IN_TRANSIT = "in_transit" # Выехал
    COMPLETED  = "completed"  # Доставил, зафиксировал факт
    CANCELLED  = "cancelled"  # Отменён


class Trip(Base):
    """Рейс водителя — одна поездка по одной заявке."""

    __tablename__ = "trips"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Ссылки на другие сервисы (cross-service, только UUID — без FK)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    driver_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )

    status: Mapped[TripStatus] = mapped_column(
        SAEnum(TripStatus), nullable=False, default=TripStatus.PLANNED, index=True
    )

    # Плановый и фактический объём
    volume_planned: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    volume_actual: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Одометр (показания счётчика)
    odometer_start: Mapped[float | None] = mapped_column(Numeric(10, 1), nullable=True)
    odometer_end: Mapped[float | None] = mapped_column(Numeric(10, 1), nullable=True)

    # Временные метки рейса
    departed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Адрес доставки (копируется из заявки на момент создания рейса)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    driver_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Денормализованный контекст для учёта топлива ─────────────
    # Заполняется менеджером при создании рейса; используется при
    # автоматическом создании FuelTransaction(departure) после завершения.
    inv_fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inv_order_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    inv_client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    inv_client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    inv_driver_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    vehicle: Mapped["Vehicle"] = relationship("Vehicle", back_populates="trips")
