from datetime import datetime
from sqlalchemy import String, Numeric, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FuelStock(Base):
    """Текущий остаток топлива на складе по каждому виду."""

    __tablename__ = "fuel_stock"

    fuel_type: Mapped[str] = mapped_column(String(50), primary_key=True)
    current_volume: Mapped[float] = mapped_column(Numeric(12, 2), default=0.0, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
