"""GPS-трекеры и их позиции (спринт 2026-09-12).

Трекеры самодельные (Arduino Nano + NEO-6M + GSM-модем), шлют точки HTTP-запросом
на отдельный порт приёма. Устройство и машина разведены: трекер живёт
своей жизнью (его переставляют с машины на машину), поэтому в позиции
сохраняется ещё и `vehicle_id` на момент приёма — чтобы история не «переехала»
задним числом при перепривязке.
"""
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Numeric, Boolean, DateTime, Text, SmallInteger, BigInteger,
    ForeignKey, Index, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class GpsDevice(Base):
    """Трекер: номер устройства из прошивки + токен доступа."""

    __tablename__ = "gps_devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Номер, зашитый в прошивку (DEVICE_ID). По нему трекер и опознаётся.
    device_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    # sha256 необязательного токена. Уже прошитые трекеры токен не шлют, но
    # поле оставлено: если его добавят (или появится новая партия устройств),
    # приём начнёт проверять подпись без миграции. NULL = проверки нет.
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Трекер завёлся сам, прислав первую точку: админ его ещё не подтверждал и
    # к машине не привязывал. В списке такие подсвечиваются как «новый».
    auto_registered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sim_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Последний контакт — обновляется даже когда фикса нет (трекер жив, но
    # спутников не видит): по нему на карте и считается «на связи / нет связи».
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Последняя валидная точка.
    last_fix_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    last_lon: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    last_sats: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    last_speed_kmh: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GpsPosition(Base):
    """Одна принятая точка. Хранится месяц, потом чистится фоновой задачей."""

    __tablename__ = "gps_positions"

    # BigInteger, а не UUID: точек много (машина на 30-секундном интервале даёт
    # ~90 тыс. строк в месяц), а по id их никто не ищет — только по времени.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gps_devices.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )

    # Время с трекера, если оно правдоподобное, иначе время приёма.
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    lon: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    sats: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # Условная погрешность по числу спутников (см. gps_protocol.ACCURACY_BY_SATS).
    accuracy_m: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    speed_kmh: Mapped[float | None] = mapped_column(Numeric(6, 1), nullable=True)

    __table_args__ = (
        Index("ix_gps_positions_device_time", "device_id", "recorded_at"),
        Index("ix_gps_positions_vehicle_time", "vehicle_id", "recorded_at"),
    )
