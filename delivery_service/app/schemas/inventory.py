import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class FuelStockResponse(BaseModel):
    fuel_type: str
    fuel_label: str
    current_volume: float
    last_updated: datetime

    model_config = {"from_attributes": True}


class ArrivalRequest(BaseModel):
    fuel_type: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Код вида топлива из каталога (напр. diesel_summer, petrol_92)",
    )
    volume: float = Field(..., gt=0, le=10_000_000, description="Объём прихода в литрах (макс. 10 000 000)")
    transaction_date: datetime | None = Field(None, description="Дата операции (по умолчанию — сейчас)")
    supplier_name: str | None = Field(None, max_length=255, description="Поставщик")
    invoice_number: str | None = Field(None, max_length=100, description="Номер накладной / счёта")
    notes: str | None = Field(None, max_length=2000)


class ExpenseRequest(BaseModel):
    """Ручной расход топлива (правки 2026-07-14): «в бак» или «иное».

    Доступен водителям и админам. Если указана ёмкость — списывается и из неё;
    counter_after опционален (заправка через колонку двигает счётчик).
    """
    fuel_type: str = Field(..., min_length=1, max_length=50)
    volume: float = Field(..., gt=0, le=10_000_000, description="Объём расхода в литрах")
    expense_kind: str = Field(..., pattern="^(tank_refuel|other)$", description="tank_refuel — в бак, other — иное")
    tank_id: uuid.UUID | None = Field(None, description="Из какой ёмкости (опционально)")
    counter_after: int | None = Field(None, ge=0, le=999_999, description="Новое показание счётчика, если лили через колонку")
    notes: str | None = Field(None, max_length=2000, description="Комментарий")


class AdjustmentRequest(BaseModel):
    """Корректировка остатка админом (правки 2026-07-11): ± литры с причиной."""
    fuel_type: str = Field(..., min_length=1, max_length=50)
    delta: float = Field(..., ge=-10_000_000, le=10_000_000, description="Изменение остатка в литрах (может быть отрицательным)")
    notes: str = Field(..., min_length=1, max_length=2000, description="Причина корректировки")


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

    # Ручной расход (правки 2026-07-14): tank_refuel | other | None
    expense_kind: str | None = None

    notes: str | None
    created_by_id: uuid.UUID
    created_at: datetime


class FuelSummary(BaseModel):
    fuel_type: str
    fuel_label: str
    opening_balance: float   # остаток ДО начала периода
    total_arrivals: float    # сумма приходов за период
    total_departures: float  # сумма расходов за период
    total_tank_refuel: float = 0.0  # из расходов — «в бак» (правки 2026-07-14)
    closing_balance: float   # остаток НА КОНЕЦ периода


class DriverExpenseSummary(BaseModel):
    """Итог по водителю за период (правки 2026-07-14): сколько всего взял
    топлива (заявки + в бак + иное) и отдельно — сколько залил в бак."""
    driver_id: uuid.UUID | None
    driver_name: str
    total_taken: float       # всё: доставки клиентам + в бак + иное
    total_tank_refuel: float # из них — в бак


class InventoryReport(BaseModel):
    period_from: datetime
    period_to: datetime
    fuel_type_filter: str | None    # None = все виды топлива
    summary: list[FuelSummary]
    driver_summary: list[DriverExpenseSummary] = []
    transactions: list[TransactionResponse]
