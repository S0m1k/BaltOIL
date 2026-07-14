"""Ёмкости для хранения топлива (правки 2026-07-14).

К одному виду топлива может относиться несколько ёмкостей. У каждой —
шестизначный счётчик колонки (литры прокачанные через неё, с переполнением
через 999999 → 0). Все операции append-only в tank_transactions: приход,
выдача по заявке, перелив, корректировка админа.
"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Numeric, DateTime, Text, Boolean, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

# Счётчик колонки — шестизначный, после 999999 обнуляется
TANK_COUNTER_MODULUS = 1_000_000


class TankTxKind(str, enum.Enum):
    ARRIVAL = "arrival"            # приход топлива в ёмкость
    ISSUE = "issue"                # выдача по заявке (водитель, по счётчику)
    TRANSFER_IN = "transfer_in"    # перелив: поступление из другой ёмкости
    TRANSFER_OUT = "transfer_out"  # перелив: уход в другую ёмкость
    ADJUST = "adjust"              # корректировка админом (литры и/или счётчик)


class FuelTank(Base):
    __tablename__ = "fuel_tanks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    fuel_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # Остаток может уходить в минус (продажа при пустом складе разрешена)
    current_volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0.0)
    # Текущее показание счётчика колонки (0..999999)
    counter: Mapped[int] = mapped_column(Numeric(10, 0), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TankTransaction(Base):
    __tablename__ = "tank_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tank_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fuel_tanks.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    kind: Mapped[TankTxKind] = mapped_column(
        SAEnum(TankTxKind, values_callable=lambda x: [e.value for e in x], name="tanktxkind"),
        nullable=False, index=True,
    )
    # Объём операции, всегда > 0; направление определяет kind
    volume: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)

    # Показания счётчика до/после (для issue — обязательны, прочие — по ситуации)
    counter_before: Mapped[int | None] = mapped_column(Numeric(10, 0), nullable=True)
    counter_after: Mapped[int | None] = mapped_column(Numeric(10, 0), nullable=True)

    # Контекст выдачи по заявке
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    order_number: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Вторая ёмкость перелива (для transfer_in/transfer_out)
    peer_tank_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    actor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
