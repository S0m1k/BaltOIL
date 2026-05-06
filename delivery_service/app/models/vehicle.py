import uuid
from datetime import datetime
from sqlalchemy import String, Numeric, Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Vehicle(Base):
    """Автотопливозаправщик (бензовоз)."""

    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Госномер — уникальный идентификатор ТС
    plate_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity_liters: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # Водитель, закреплённый за ТС (может быть None — свободная машина)
    assigned_driver_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    trips: Mapped[list["Trip"]] = relationship("Trip", back_populates="vehicle")
