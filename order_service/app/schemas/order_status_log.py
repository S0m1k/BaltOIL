import uuid
from datetime import datetime
from pydantic import BaseModel
from app.models.order import OrderStatus


class OrderStatusLogResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    from_status: OrderStatus | None
    to_status: OrderStatus
    changed_by_id: uuid.UUID | None
    changed_by_role: str | None
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
