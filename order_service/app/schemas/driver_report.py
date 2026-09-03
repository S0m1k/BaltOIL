import uuid
from datetime import datetime
from pydantic import BaseModel


class DriverOrderInfo(BaseModel):
    """Доставленная водителем заявка — для отчёта в delivery_service."""

    order_id: uuid.UUID
    order_number: str
    order_kind: str      # вид заявки: individual|company|ttn_l — секции отчёта
    ttn_number: str | None = None
    fuel_type: str
    volume_delivered: float | None
    delivery_address: str
    client_id: uuid.UUID
    delivered_at: datetime
    comment: str | None = None

    model_config = {"from_attributes": True}
