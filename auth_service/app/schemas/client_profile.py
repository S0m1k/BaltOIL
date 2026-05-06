import uuid
from datetime import datetime
from pydantic import BaseModel
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
    legal_address: str | None
    bank_account: str | None
    bank_name: str | None
    bik: str | None
    correspondent_account: str | None
    contract_number: str | None
    credit_allowed: bool

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UpdateClientProfileRequest(BaseModel):
    delivery_address: str | None = None
    notes: str | None = None

    # Individual
    passport_series: str | None = None
    passport_number: str | None = None

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
