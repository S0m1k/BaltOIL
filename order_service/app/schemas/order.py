import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from app.models.order import FuelType, OrderStatus, PaymentType, OrderPriority
from .order_status_log import OrderStatusLogResponse


class OrderCreateRequest(BaseModel):
    fuel_type: FuelType
    volume_requested: float = Field(..., gt=0, le=200_000, description="Объём в литрах, минимум 1000, максимум 200 000")
    delivery_address: str
    desired_date: datetime | None = None
    payment_type: PaymentType = PaymentType.ON_DELIVERY
    client_comment: str | None = None

    # Только для менеджера/админа: создать от имени конкретного клиента
    client_id: uuid.UUID | None = None
    # Только для менеджера/админа: сразу поставить статус «в работе»
    start_in_progress: bool = False
    priority: OrderPriority = OrderPriority.NORMAL
    manager_comment: str | None = None

    @field_validator("volume_requested")
    @classmethod
    def min_volume(cls, v: float) -> float:
        if v < 1000:
            raise ValueError("Минимальный объём заказа — 1000 литров")
        return v


class OrderUpdateRequest(BaseModel):
    """Менеджер может обновить приоритет, комментарий и желаемую дату."""
    priority: OrderPriority | None = None
    manager_comment: str | None = None
    desired_date: datetime | None = None


class OrderStatusTransitionRequest(BaseModel):
    """Запрос на смену статуса с опциональным комментарием."""
    to_status: OrderStatus
    comment: str | None = None
    # Для водителя при завершении рейса
    volume_delivered: float | None = Field(None, gt=0)
    # Для менеджера при отклонении
    rejection_reason: str | None = None
    # Для менеджера при назначении водителя
    driver_id: uuid.UUID | None = None


class OrderResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    client_id: uuid.UUID
    fuel_type: FuelType
    volume_requested: float
    volume_delivered: float | None
    delivery_address: str
    desired_date: datetime | None
    payment_type: PaymentType
    payment_status: str
    status: OrderStatus
    priority: OrderPriority
    manager_id: uuid.UUID | None
    driver_id: uuid.UUID | None
    client_comment: str | None
    manager_comment: str | None
    rejection_reason: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    status_logs: list[OrderStatusLogResponse] = []

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    client_id: uuid.UUID
    fuel_type: FuelType
    volume_requested: float
    volume_delivered: float | None
    delivery_address: str
    status: OrderStatus
    priority: OrderPriority
    manager_id: uuid.UUID | None
    driver_id: uuid.UUID | None
    client_comment: str | None
    manager_comment: str | None
    payment_type: PaymentType
    payment_status: str
    desired_date: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}
