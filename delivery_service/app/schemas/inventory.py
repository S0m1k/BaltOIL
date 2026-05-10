import uuid
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.fuel_transaction import FUEL_TYPE_LABELS


class FuelStockResponse(BaseModel):
    fuel_type: str
    fuel_label: str
    current_volume: float
    last_updated: datetime

    model_config = {"from_attributes": True}


class ArrivalRequest(BaseModel):
    fuel_type: str = Field(
        ...,
        pattern="^(diesel_summer|diesel_winter|petrol_92|petrol_95|fuel_oil)$",
        description="Вид топлива: diesel_summer / diesel_winter / petrol_92 / petrol_95 / fuel_oil",
    )
    volume: float = Field(..., gt=0, le=10_000_000, description="Объём прихода в литрах (макс. 10 000 000)")
    transaction_date: datetime | None = Field(None, description="Дата операции (по умолчанию — сейчас)")
    supplier_name: str | None = Field(None, max_length=255, description="Поставщик")
    invoice_number: str | None = Field(None, max_length=100, description="Номер накладной / счёта")
    notes: str | None = Field(None, max_length=2000)


class TransactionResponse(BaseModel):
    id: uuid.UUID
    type: str                      # "arrival" | "departure"
    fuel_type: str
    fuel_label: str
    volume: float
    transaction_date: datetime

    # Расход — контекст рейса
    trip_id: uuid.UUID | None
    order_id: uuid.UUID | None
    order_number: str | None
    client_id: uuid.UUID | None
    client_name: str | None
    driver_id: uuid.UUID | None
    driver_name: str | None

    # Приход — контекст поставки
    supplier_name: str | None
    invoice_number: str | None

    notes: str | None
    created_by_id: uuid.UUID
    created_at: datetime


class FuelSummary(BaseModel):
    fuel_type: str
    fuel_label: str
    opening_balance: float   # остаток ДО начала периода
    total_arrivals: float    # сумма приходов за период
    total_departures: float  # сумма расходов за период
    closing_balance: float   # остаток НА КОНЕЦ периода


class InventoryReport(BaseModel):
    period_from: datetime
    period_to: datetime
    fuel_type_filter: str | None    # None = все виды топлива
    summary: list[FuelSummary]
    transactions: list[TransactionResponse]
