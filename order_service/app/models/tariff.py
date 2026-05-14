import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Boolean, Numeric, DateTime, func, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Exactly one active tariff must have is_default=True — enforced in service layer
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    fuel_prices: Mapped[list["TariffFuelPrice"]] = relationship(
        "TariffFuelPrice", back_populates="tariff", cascade="all, delete-orphan"
    )
    volume_tiers: Mapped[list["TariffVolumeTier"]] = relationship(
        "TariffVolumeTier",
        back_populates="tariff",
        cascade="all, delete-orphan",
        order_by="TariffVolumeTier.min_volume",
    )


class TariffFuelPrice(Base):
    __tablename__ = "tariff_fuel_prices"
    __table_args__ = (
        UniqueConstraint("tariff_id", "fuel_type", name="uq_tariff_fuel_prices"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tariff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        # FK defined without SA ForeignKey to keep models importable without full migration state
        nullable=False,
        index=True,
    )
    # Stored as string matching FuelType enum VALUES ('DIESEL_SUMMER' etc.)
    fuel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    price_per_liter: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)

    tariff: Mapped["Tariff"] = relationship("Tariff", back_populates="fuel_prices")


class TariffVolumeTier(Base):
    __tablename__ = "tariff_volume_tiers"
    __table_args__ = (
        UniqueConstraint("tariff_id", "min_volume", name="uq_tariff_volume_tiers"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tariff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Lower bound (inclusive) in litres for this discount tier
    min_volume: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Percentage off base price, e.g. Decimal("10.00") means 10%
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    tariff: Mapped["Tariff"] = relationship("Tariff", back_populates="volume_tiers")
