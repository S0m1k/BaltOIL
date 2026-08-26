import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Boolean, Numeric, DateTime, ForeignKey, func, UniqueConstraint
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
    # Базовая стоимость доставки (умножается на cost_coefficient зоны)
    base_delivery_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0")
    )
    # individual | company | None (None = не привязан к типу клиента)
    client_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    # ── Формульный тариф (CRM-33): цены считаются от базового при чтении ──
    # Если base_tariff_id задан — собственные цены игнорируются, а берутся
    # цены базового тарифа с наценкой/скидкой (formula_type/formula_value).
    base_tariff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tariffs.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    # percent | fixed | None
    formula_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Знаковое: +5 = наценка, −5 = скидка (в % или ₽/л по formula_type)
    formula_value: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
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
        UUID(as_uuid=True), ForeignKey("tariffs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Stored as string matching FuelType enum VALUES ('DIESEL_SUMMER' etc.)
    fuel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # NULL допустим только для скрытых видов (глазик выключен, цена не задана)
    price_per_liter: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    # «Глазик» (CRM-33): скрытый вид топлива не требует цены и не предлагается
    # клиенту при заказе по этому тарифу
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

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
        UUID(as_uuid=True), ForeignKey("tariffs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Lower bound (inclusive) in litres for this discount tier
    min_volume: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Percentage off base price, e.g. Decimal("10.00") means 10%
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)

    tariff: Mapped["Tariff"] = relationship("Tariff", back_populates="volume_tiers")


class TariffPriceHistory(Base):
    """Журнал изменений цен тарифа (CRM-32): кто, когда, топливо, было → стало.

    Пишется при создании и правке тарифа. Бэкфилла нет — история ведётся
    с момента деплоя.
    """

    __tablename__ = "tariff_price_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tariff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tariffs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    fuel_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # added | price | removed | hidden | shown
    change_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    new_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    changed_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    changed_by_role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
