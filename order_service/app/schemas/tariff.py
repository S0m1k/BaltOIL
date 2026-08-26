import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class FuelPriceIn(BaseModel):
    fuel_type: str = Field(..., description="FuelType enum value, e.g. DIESEL_SUMMER")
    # Цена обязательна только для видимых видов топлива (глазик включён).
    # Для скрытых (is_hidden=True) допускается null — валидация в сервисе.
    price_per_liter: Decimal | None = Field(None, gt=0, decimal_places=4)
    # «Глазик» (CRM-33): скрытый вид не требует цены и не предлагается клиенту
    is_hidden: bool = False


class VolumeTierIn(BaseModel):
    min_volume: Decimal = Field(..., ge=0, decimal_places=2,
                                description="Inclusive lower bound in litres")
    discount_pct: Decimal = Field(..., ge=0, le=100, decimal_places=2,
                                  description="Percentage discount off base price")


class TariffCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    fuel_prices: list[FuelPriceIn] = Field(..., min_length=1)
    volume_tiers: list[VolumeTierIn] = Field(default_factory=list)
    # individual | company | None
    client_type: str | None = None
    # Стоимость доставки за литр, ₽ (умножается на коэффициент зоны и клиента).
    # Убрана из UI тарифа (правки 2026-08-26), поле остаётся для совместимости.
    base_delivery_cost: Decimal = Field(Decimal("0"), ge=0, le=Decimal("1000"), decimal_places=2)
    # ── Формульный тариф: цены от базового ──
    base_tariff_id: uuid.UUID | None = None
    formula_type: str | None = Field(None, description="percent | fixed")
    formula_value: Decimal | None = Field(None, decimal_places=4,
                                          description="Знаковое: +наценка / −скидка")


class TariffUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    fuel_prices: list[FuelPriceIn] = Field(..., min_length=1)
    volume_tiers: list[VolumeTierIn] = Field(default_factory=list)
    # When present (even if None), admin may update client_type
    client_type: str | None = Field(default=None)
    base_delivery_cost: Decimal | None = Field(None, ge=0, le=Decimal("1000"), decimal_places=2)
    # Формула: поля применяются только если явно присланы (model_fields_set)
    base_tariff_id: uuid.UUID | None = None
    formula_type: str | None = None
    formula_value: Decimal | None = Field(None, decimal_places=4)


class FuelPriceResponse(BaseModel):
    id: uuid.UUID | None = None
    fuel_type: str
    price_per_liter: Decimal | None = None
    is_hidden: bool = False

    model_config = {"from_attributes": True}


class VolumeTierResponse(BaseModel):
    id: uuid.UUID
    min_volume: Decimal
    discount_pct: Decimal

    model_config = {"from_attributes": True}


class TariffResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_default: bool
    description: str | None
    is_archived: bool
    base_delivery_cost: Decimal
    client_type: str | None = None
    fuel_prices: list[FuelPriceResponse]
    volume_tiers: list[VolumeTierResponse]
    created_at: datetime
    updated_at: datetime
    # Формульный тариф
    base_tariff_id: uuid.UUID | None = None
    base_tariff_name: str | None = None
    formula_type: str | None = None
    formula_value: Decimal | None = None
    # Итоговые цены после применения формулы (для обычных тарифов совпадают
    # с fuel_prices). Клиентам и расчётам следует смотреть сюда.
    effective_fuel_prices: list[FuelPriceResponse] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class TariffPriceHistoryResponse(BaseModel):
    id: uuid.UUID
    tariff_id: uuid.UUID
    fuel_type: str
    change_kind: str
    old_price: Decimal | None
    new_price: Decimal | None
    changed_by_id: uuid.UUID | None
    changed_by_role: str | None
    changed_at: datetime

    model_config = {"from_attributes": True}


class ClientPaymentOptionsResponse(BaseModel):
    """Available payment types for a given client, for dynamic UI rendering."""
    client_id: uuid.UUID
    client_type: str
    available_payment_types: list[str]
