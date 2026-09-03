import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class OrderKindFilter(str, Enum):
    """Вид заявки — дублирует order_service OrderKind: межсервисного импорта нет,
    а FastAPI нужен enum, чтобы отбить неизвестное значение 422-й, а не запросом в БД."""

    INDIVIDUAL = "individual"
    COMPANY    = "company"
    TTN_L      = "ttn_l"


class DriverOrderItem(BaseModel):
    """Доставленная заявка в отчёте водителя."""

    order_id: uuid.UUID
    order_number: str
    order_kind: str = ""     # individual|company|ttn_l — секции отчёта
    ttn_number: str | None = None
    fuel_type: str
    volume_delivered: float | None
    delivery_address: str
    client_id: uuid.UUID
    delivered_at: datetime
    comment: str | None = None


class DriverReportResponse(BaseModel):
    driver_id: uuid.UUID
    period_from: datetime
    period_to: datetime

    total_orders: int
    total_volume_delivered: float

    orders: list[DriverOrderItem]
