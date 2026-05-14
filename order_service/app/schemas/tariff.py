import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


class FuelPriceIn(BaseModel):
    fuel_type: str = Field(..., description="FuelType enum value, e.g. DIESEL_SUMMER")
    price_per_liter: Decimal = Field(..., gt=0, decimal_places=4)


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


class TariffUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = None
    fuel_prices: list[FuelPriceIn] = Field(..., min_length=1)
    volume_tiers: list[VolumeTierIn] = Field(default_factory=list)


class FuelPriceResponse(BaseModel):
    id: uuid.UUID
    fuel_type: str
    price_per_liter: Decimal

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
    fuel_prices: list[FuelPriceResponse]
    volume_tiers: list[VolumeTierResponse]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClientPaymentOptionsResponse(BaseModel):
    """Available payment types for a given client, for dynamic UI rendering."""
    client_id: uuid.UUID
    client_type: str
    available_payment_types: list[str]
