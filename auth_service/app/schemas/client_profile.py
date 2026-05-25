import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field
from app.models.client_profile import ClientType


class ClientProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    client_type: ClientType
    delivery_address: str | None
    notes: str | None

    # Individual
    passport_series: str | None
    passport_number: str | None

    # Company
    company_name: str | None
    inn: str | None
    kpp: str | None
    ogrn: str | None = None
    legal_address: str | None
    bank_account: str | None
    bank_name: str | None
    bik: str | None
    correspondent_account: str | None
    contract_number: str | None
    credit_allowed: bool
    credit_limit: Decimal | None
    tariff_id: uuid.UUID | None
    fuel_coefficient: float
    delivery_coefficient: float
    client_number: int | None

    # FNS-extra (DaData)
    okved: str | None = None
    okpo: str | None = None
    okato: str | None = None
    fns_status: str | None = None
    director_name: str | None = None
    swift: str | None = None
    billing_email: str | None = None
    fns_last_sync_at: datetime | None = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateClientProfileRequest(BaseModel):
    delivery_address: str | None = None
    notes: str | None = None

    # Company
    company_name: str | None = None
    inn: str | None = None
    kpp: str | None = None
    legal_address: str | None = None
    bank_account: str | None = None
    bank_name: str | None = None
    bik: str | None = None
    correspondent_account: str | None = None
    contract_number: str | None = None
    billing_email: str | None = None


class UpdateClientTariffRequest(BaseModel):
    """Назначение тарифа и управление кредитным флагом — только admin."""
    # Soft FK — ссылается на tariffs.id в order_service БД. NULL = использовать default.
    tariff_id: uuid.UUID | None = Field(None)
    credit_allowed: bool | None = Field(None)
    credit_limit: Decimal | None = Field(None, ge=0)
    # Устаревшие коэффициенты — оставлены для совместимости до удаления полей.
    fuel_coefficient: float | None = Field(None, gt=0, le=5.0)
    delivery_coefficient: float | None = Field(None, gt=0, le=5.0)
