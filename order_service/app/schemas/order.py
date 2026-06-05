import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator
from app.models.order import OrderStatus, OrderKind, PaymentType
from .order_status_log import OrderStatusLogResponse


class OrderCreateRequest(BaseModel):
    fuel_type: str
    volume_requested: float = Field(..., gt=0, le=200_000, description="Объём в литрах, минимум 300, максимум 200 000")
    delivery_address: str
    desired_date: datetime | None = None
    payment_type: PaymentType = PaymentType.ON_DELIVERY
    expected_amount: Decimal | None = Field(None, ge=0, description="Ожидаемая сумма оплаты")
    client_comment: str | None = None

    # Только для менеджера/админа: создать от имени конкретного клиента
    client_id: uuid.UUID | None = None
    manager_comment: str | None = None
    # Назначить конкретного водителя (NULL = все видят, пул)
    driver_id: uuid.UUID | None = None
    # Создать как ТТН-Л (только менеджер)
    is_ttn_l: bool = False

    @field_validator("volume_requested")
    @classmethod
    def min_volume(cls, v: float) -> float:
        if v < 300:
            raise ValueError("Минимальный объём заказа — 300 литров")
        return v


class OrderUpdateRequest(BaseModel):
    """Менеджер/Админ могут обновить любые поля заявки в любом статусе."""
    manager_comment: str | None = None
    desired_date: datetime | None = None
    driver_id: uuid.UUID | None = None
    expected_amount: Decimal | None = Field(None, ge=0)
    final_amount: Decimal | None = Field(None, ge=0)
    trade_credit_contract_signed: bool | None = None
    delivery_address: str | None = None
    fuel_type: str | None = None
    volume_requested: float | None = Field(None, gt=0)
    payment_type: PaymentType | None = None
    client_comment: str | None = None


class OrderStatusTransitionRequest(BaseModel):
    """Запрос на смену статуса с опциональным комментарием."""
    to_status: OrderStatus
    comment: str | None = None
    # Для водителя при завершении рейса — обязательно при ACCEPTED→DELIVERED
    ttn_number: str | None = None
    # Для менеджера при отмене
    rejection_reason: str | None = None


class RescheduleRequest(BaseModel):
    """Перенос заявки: смена желаемой даты и/или водителя."""
    desired_date: datetime | None = None
    driver_id: uuid.UUID | None = None


class OrderResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    order_kind: OrderKind
    client_id: uuid.UUID
    fuel_type: str
    volume_requested: float
    volume_delivered: float | None
    delivery_address: str
    desired_date: datetime | None
    ttn_number: str | None
    pending_driver_ack: bool
    payment_type: PaymentType
    payment_status: str
    expected_amount: Decimal | None
    final_amount: Decimal | None
    trade_credit_contract_signed: bool
    status: OrderStatus
    manager_id: uuid.UUID | None
    driver_id: uuid.UUID | None
    client_comment: str | None
    manager_comment: str | None
    rejection_reason: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    status_logs: list[OrderStatusLogResponse] = []

    # Денежные показатели — заполняются сервисом (см. payment_service.attach_payment_totals)
    paid_total: float = 0.0
    debt_amount: float = 0.0
    pricing_warning: bool = False  # True если expected_amount=None (тариф не настроен)

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    order_kind: OrderKind
    client_id: uuid.UUID
    fuel_type: str
    volume_requested: float
    volume_delivered: float | None
    delivery_address: str
    status: OrderStatus
    ttn_number: str | None
    pending_driver_ack: bool
    manager_id: uuid.UUID | None
    driver_id: uuid.UUID | None
    client_comment: str | None
    manager_comment: str | None
    payment_type: PaymentType
    payment_status: str
    rejection_reason: str | None = None
    expected_amount: Decimal | None
    final_amount: Decimal | None
    desired_date: datetime | None
    created_at: datetime

    paid_total: float = 0.0
    debt_amount: float = 0.0
    pricing_warning: bool = False

    model_config = {"from_attributes": True}
