"""Схемы перевозки: справочники + заявка на перевозку."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.transport import TransportType, RoutePointKind

# ── Справочник: нефтебазы ─────────────────────────────────────────────────────


class TransportBaseCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    default_delivery_cost: Decimal | None = Field(None, ge=0)


class TransportBaseUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    default_delivery_cost: Decimal | None = Field(None, ge=0)
    is_active: bool | None = None


class TransportBaseResponse(BaseModel):
    id: uuid.UUID
    name: str
    default_delivery_cost: Decimal | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Справочник: объекты клиентов ──────────────────────────────────────────────


class TransportClientAddressResponse(BaseModel):
    id: uuid.UUID
    address: str
    sort_order: int

    model_config = {"from_attributes": True}


class TransportClientObjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    # Прикреплённый клиент (user_id). Необязателен: объект можно завести заранее.
    client_id: uuid.UUID | None = None
    addresses: list[str] = Field(default_factory=list, max_length=50)


class TransportClientObjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    client_id: uuid.UUID | None = None
    # Полная замена списка адресов. None = не трогать.
    addresses: list[str] | None = Field(None, max_length=50)
    is_active: bool | None = None


class TransportClientObjectResponse(BaseModel):
    id: uuid.UUID
    name: str
    client_id: uuid.UUID | None
    contract_file_name: str | None
    has_contract: bool = False
    is_active: bool
    addresses: list[TransportClientAddressResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Заявка на перевозку ───────────────────────────────────────────────────────


class RoutePoint(BaseModel):
    """Точка маршрута: вид + ссылка на справочник (или свободный текст)."""

    kind: RoutePointKind
    id: uuid.UUID | None = None
    text: str | None = Field(None, max_length=500)


class TransportOrderCreateRequest(BaseModel):
    # ── Блок 1 (виден водителю) ──
    transport_type: TransportType
    client_object_id: uuid.UUID | None = None
    route_from: RoutePoint | None = None
    route_to: RoutePoint | None = None
    waypoints: list[RoutePoint] = Field(default_factory=list, max_length=3)
    amount_kg: Decimal | None = Field(None, ge=0)
    amount_l: Decimal | None = Field(None, ge=0)
    # Вид топлива из каталога; по ТЗ можно оставить пустым.
    fuel_type: str | None = None
    desired_date_text: str | None = Field(None, max_length=500)
    comment: str | None = None

    # ── Блок 2 (только staff, все поля опциональны) ──
    price_per_kg: Decimal | None = Field(None, ge=0)
    price_per_l: Decimal | None = Field(None, ge=0)
    density: Decimal | None = Field(None, ge=0)
    total_amount: Decimal | None = Field(None, ge=0)
    supplier_payments: list[dict] = Field(default_factory=list, max_length=4)
    delivery_price: Decimal | None = Field(None, ge=0)
    delivery_paid: bool = False
    driver_payment_amount: Decimal | None = Field(None, ge=0)
    driver_payment_percent: Decimal | None = Field(None, ge=0, le=100)

    # Водитель назначается автоматически (перевозки видит только он), но админ
    # может указать явно — на случай подмены водителя перевозок.
    driver_id: uuid.UUID | None = None

    @field_validator("waypoints")
    @classmethod
    def _max_three_waypoints(cls, v: list) -> list:
        if len(v) > 3:
            raise ValueError("Промежуточных точек может быть не больше трёх")
        return v


class TransportOrderUpdateRequest(BaseModel):
    """После отправки заявки можно менять ЛЮБОЕ поле (ТЗ, п. 3).

    Отличать «не передано» от «передан null» важно: null — валидное значение
    для очистки поля, поэтому сервис смотрит на ``model_fields_set``.
    """

    transport_type: TransportType | None = None
    client_object_id: uuid.UUID | None = None
    route_from: RoutePoint | None = None
    route_to: RoutePoint | None = None
    waypoints: list[RoutePoint] | None = Field(None, max_length=3)
    amount_kg: Decimal | None = Field(None, ge=0)
    amount_l: Decimal | None = Field(None, ge=0)
    fuel_type: str | None = None
    desired_date_text: str | None = Field(None, max_length=500)
    comment: str | None = None

    price_per_kg: Decimal | None = Field(None, ge=0)
    price_per_l: Decimal | None = Field(None, ge=0)
    density: Decimal | None = Field(None, ge=0)
    total_amount: Decimal | None = Field(None, ge=0)
    supplier_payments: list[dict] | None = Field(None, max_length=4)
    delivery_price: Decimal | None = Field(None, ge=0)
    delivery_paid: bool | None = None
    driver_payment_amount: Decimal | None = Field(None, ge=0)
    driver_payment_percent: Decimal | None = Field(None, ge=0, le=100)
    driver_id: uuid.UUID | None = None


class TransportDeliverRequest(BaseModel):
    """Окно «доставлено» у водителя: маршрут и дата обязательны и правятся.

    Комментарий — единственное необязательное поле (ТЗ, п. 3).
    """

    route_from: RoutePoint
    route_to: RoutePoint
    waypoints: list[RoutePoint] = Field(default_factory=list, max_length=3)
    desired_date_text: str = Field(..., min_length=1, max_length=500)
    comment: str | None = None
    idempotency_key: uuid.UUID | None = None


class TransportDetailResponse(BaseModel):
    """Детали перевозки. Блок 2 обнуляется для не-staff (см. transport_service)."""

    transport_type: str
    client_object_id: uuid.UUID | None = None
    route_from: RoutePoint | None = None
    route_to: RoutePoint | None = None
    waypoints: list[RoutePoint] = []
    amount_kg: Decimal | None = None
    amount_l: Decimal | None = None
    desired_date_text: str | None = None

    # Блок 2 — только менеджеру и админу
    price_per_kg: Decimal | None = None
    price_per_l: Decimal | None = None
    density: Decimal | None = None
    total_amount: Decimal | None = None
    supplier_payments: list[dict] = []
    delivery_price: Decimal | None = None
    delivery_paid: bool = False
    driver_payment_amount: Decimal | None = None
    driver_payment_percent: Decimal | None = None
    # Вычисляемые подсказки (сервер — источник истины по формулам)
    supplier_paid_total: Decimal | None = None


class TransportFinanceRow(BaseModel):
    """Строка перевозки в финансовом отчёте: расход/приход помечены «Перевозка»."""

    order_id: uuid.UUID
    order_number: str
    ttn_number: str | None = None
    transport_type: str
    route: str
    status: str
    created_at: datetime
    direction: Literal["expense", "income"]
    # «Оплата поставщику» / «Стоимость доставки» / «Оплата водителю»
    article: str
    amount: Decimal
    paid_at: str | None = None
    is_paid: bool = True
