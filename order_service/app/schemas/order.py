import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from app.models.order import OrderStatus, OrderKind, PaymentType
from .order_status_log import OrderStatusLogResponse


class PricePreviewRequest(BaseModel):
    fuel_type: str
    volume: float = Field(..., gt=0)
    delivery_lat: float | None = Field(None, ge=-90, le=90)
    delivery_lon: float | None = Field(None, ge=-180, le=180)
    client_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None


class PricePreviewResponse(BaseModel):
    fuel_type: str
    volume: float
    price_per_liter: Decimal | None
    discount_pct: Decimal
    effective_price_per_liter: Decimal | None
    fuel_subtotal: Decimal | None
    zone_name: str | None
    zone_cost_coefficient: float | None
    base_delivery_cost: Decimal | None
    delivery_cost: Decimal | None
    total: Decimal | None
    pricing_warning: bool


class OrderCreateRequest(BaseModel):
    fuel_type: str
    volume_requested: float = Field(..., gt=0, le=200_000, description="Объём в литрах, минимум 300, максимум 200 000")
    delivery_address: str
    desired_date: datetime | None = None
    # Контактное лицо для приёмки топлива на объекте
    contact_person_name: str | None = Field(None, max_length=120)
    contact_person_phone: str | None = Field(None, max_length=20)
    payment_type: PaymentType = PaymentType.ON_DELIVERY
    expected_amount: Decimal | None = Field(None, ge=0, description="Ожидаемая сумма оплаты")
    client_comment: str | None = None

    # Организация (юрлицо), от имени которой создаётся заявка. NULL = «как физлицо».
    # Членство клиента проверяется в auth_service при резолве контекста.
    organization_id: uuid.UUID | None = None

    # Координаты адреса доставки (из DaData-геокодирования на фронте)
    delivery_lat: float | None = Field(None, ge=-90, le=90)
    delivery_lon: float | None = Field(None, ge=-180, le=180)

    # Только для менеджера/админа: создать от имени конкретного клиента
    client_id: uuid.UUID | None = None
    manager_comment: str | None = None
    # Назначить конкретного водителя (NULL = все видят, пул)
    driver_id: uuid.UUID | None = None
    # Создать как ТТН-Л (только менеджер)
    is_ttn_l: bool = False
    # Долговая заявка: доставка без оплаты (только менеджер/админ, для клиента игнорируется)
    allow_delivery_unpaid: bool = False

    # Минимальный объём (300 л) проверяется в order_service.create_order,
    # т.к. менеджер/админ может оформить заявку на любой объём (правка 2026-06-16).


class OrderUpdateRequest(BaseModel):
    """Менеджер/Админ — любые поля в любом статусе.
    Клиент/водитель — ограниченный набор (топливо/объём/адрес/дата),
    права проверяются в order_service.update_order."""
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
    contact_person_name: str | None = Field(None, max_length=120)
    contact_person_phone: str | None = Field(None, max_length=20)
    # Стоимость доставки: менеджер может проставить вручную для адресов вне зоны
    delivery_cost: Decimal | None = Field(None, ge=0)
    # Долговая заявка: менеджер/админ может переключить флаг
    allow_delivery_unpaid: bool | None = None


class OrderStatusTransitionRequest(BaseModel):
    """Запрос на смену статуса с опциональным комментарием."""
    to_status: OrderStatus
    comment: str | None = None
    # Для водителя при завершении рейса — обязательно при ACCEPTED→DELIVERED
    ttn_number: str | None = None
    # Фактически отгруженный объём (л) при ACCEPTED→DELIVERED; NULL = как заказано
    volume_delivered: float | None = Field(None, gt=0, le=200_000)
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
    organization_id: uuid.UUID | None = None
    fuel_type: str
    volume_requested: float
    volume_delivered: float | None
    delivery_address: str
    desired_date: datetime | None
    contact_person_name: str | None = None
    contact_person_phone: str | None = None
    ttn_number: str | None
    pending_driver_ack: bool
    pending_changed_fields: list[str] | None = None
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

    # Зона доставки (снимок на момент создания)
    delivery_lat: Decimal | None = None
    delivery_lon: Decimal | None = None
    delivery_zone_id: uuid.UUID | None = None
    delivery_zone_name: str | None = None
    delivery_cost: Decimal | None = None

    allow_delivery_unpaid: bool = False

    # Денежные показатели — заполняются сервисом (см. payment_service.attach_payment_totals)
    paid_total: float = 0.0
    debt_amount: float = 0.0
    pricing_warning: bool = False  # True если expected_amount=None (тариф не настроен)

    # Имя покупателя: организация, иначе ФИО клиента (правки 2026-06-23)
    buyer_name: str | None = None

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    id: uuid.UUID
    order_number: str
    order_kind: OrderKind
    client_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    fuel_type: str
    volume_requested: float
    volume_delivered: float | None
    delivery_address: str
    status: OrderStatus
    ttn_number: str | None
    pending_driver_ack: bool
    pending_changed_fields: list[str] | None = None
    contact_person_name: str | None = None
    contact_person_phone: str | None = None
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

    delivery_zone_name: str | None = None
    delivery_cost: Decimal | None = None

    allow_delivery_unpaid: bool = False

    paid_total: float = 0.0
    debt_amount: float = 0.0
    pricing_warning: bool = False

    # Имя покупателя: организация, иначе ФИО клиента (правки 2026-06-23)
    buyer_name: str | None = None

    model_config = {"from_attributes": True}
