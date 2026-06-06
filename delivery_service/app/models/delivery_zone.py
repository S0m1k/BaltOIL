"""Зона доставки с полигоном (JSONB) и коэффициентом стоимости."""
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Boolean, Numeric, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class DeliveryZone(Base):
    __tablename__ = "delivery_zones"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Список координат [[lat, lng], ...] — конвенция Leaflet
    polygon: Mapped[list] = mapped_column(JSONB, nullable=False)
    cost_coefficient: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False, default=Decimal("1.0")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
