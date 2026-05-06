from pydantic import BaseModel
from app.models.order import FuelType

# Человекочитаемые названия и единица измерения
FUEL_TYPE_META: dict[FuelType, dict] = {
    FuelType.DIESEL_SUMMER: {"name": "Дизельное топливо летнее", "short": "ДТ-Л", "unit": "л"},
    FuelType.DIESEL_WINTER: {"name": "Дизельное топливо зимнее", "short": "ДТ-З", "unit": "л"},
    FuelType.PETROL_92:     {"name": "Бензин Регуляр-92",        "short": "АИ-92", "unit": "л"},
    FuelType.PETROL_95:     {"name": "Бензин Премиум-95",        "short": "АИ-95", "unit": "л"},
    FuelType.FUEL_OIL:      {"name": "Топочный мазут М-100",     "short": "М-100", "unit": "л"},
}


class FuelTypeInfo(BaseModel):
    code: FuelType
    name: str
    short: str
    unit: str
