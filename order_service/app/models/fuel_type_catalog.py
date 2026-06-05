from sqlalchemy import String, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class FuelTypeCatalog(Base):
    """Каталог видов топлива — источник истины для всех сервисов."""

    __tablename__ = "fuel_types"

    # Код вида топлива — первичный ключ (напр. "diesel_summer")
    code: Mapped[str] = mapped_column(String(50), primary_key=True)
    # Отображаемое название (напр. "ДТ-Л К5")
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    # Зимнее топливо (для сезонного дефолта в форме заявки)
    is_winter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Порядок сортировки в списках
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Мягкое удаление — деактивированные коды не предлагаются, но хранятся
    # (исторические заявки ссылаются на код)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
