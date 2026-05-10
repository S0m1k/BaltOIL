import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Numeric, DateTime, Text, Enum as SAEnum, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class TransactionType(str, enum.Enum):
    ARRIVAL = "arrival"      # Приход топлива на склад
    DEPARTURE = "departure"  # Расход топлива (рейс)


FUEL_TYPE_LABELS: dict[str, str] = {
    "diesel_summer": "ДТ-Л",
    "diesel_winter": "ДТ-З",
    "petrol_92":     "АИ-92",
    "petrol_95":     "АИ-95",
    "fuel_oil":      "М-100",
}

FUEL_TYPES = list(FUEL_TYPE_LABELS.keys())


class FuelTransaction(Base):
    """Операция прихода или расхода топлива."""

    __tablename__ = "fuel_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[TransactionType] = mapped_column(
        SAEnum(TransactionType), nullable=False, index=True
    )
    fuel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)  # всегда > 0

    transaction_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    # Контекст для расходов (рейсы)
    trip_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    order_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Контекст для приходов
    supplier_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
