import uuid
from datetime import datetime
from pydantic import BaseModel


class DriverOrderItem(BaseModel):
    """Доставленная заявка в отчёте водителя."""

    order_id: uuid.UUID
    order_number: str
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
