import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field

from app.models.organization import MemberRole, MemberStatus


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    org_number: int
    company_name: str
    inn: str | None
    kpp: str | None
    ogrn: str | None
    legal_address: str | None
    delivery_address: str | None
    bank_name: str | None
    bik: str | None
    bank_account: str | None
    correspondent_account: str | None
    swift: str | None
    contract_number: str | None
    billing_email: str | None
    okved: str | None
    okpo: str | None
    okato: str | None
    fns_status: str | None
    director_name: str | None
    fns_last_sync_at: datetime | None

    tariff_id: uuid.UUID | None
    credit_allowed: bool
    credit_limit: Decimal | None
    fuel_coefficient: float
    delivery_coefficient: float

    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrganizationMemberResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID | None
    invite_phone: str | None
    member_role: MemberRole
    status: MemberStatus
    created_at: datetime
    # Резолвится из User (если user_id есть)
    full_name: str | None = None
    phone: str | None = None

    model_config = {"from_attributes": True}


class CreateOrganizationRequest(BaseModel):
    """Создание организации клиентом. ИНН обязателен — по нему тянем DaData.
    Реквизиты можно дозаполнить/переопределить вручную, если DaData недоступна."""
    inn: str = Field(..., min_length=10, max_length=12)
    bik: str | None = Field(None, min_length=9, max_length=9)
    company_name: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    legal_address: str | None = None
    delivery_address: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    correspondent_account: str | None = None
    contract_number: str | None = None
    billing_email: str | None = None


class UpdateOrganizationRequest(BaseModel):
    """Правка реквизитов организации (owner/admin). DaData-поля read-only."""
    company_name: str | None = None
    kpp: str | None = None
    legal_address: str | None = None
    delivery_address: str | None = None
    bank_name: str | None = None
    bik: str | None = None
    bank_account: str | None = None
    correspondent_account: str | None = None
    contract_number: str | None = None
    billing_email: str | None = None
    director_name: str | None = None  # ручное переопределение
    swift: str | None = None


class UpdateOrganizationCommercialRequest(BaseModel):
    """Тариф/кредит организации — только admin."""
    tariff_id: uuid.UUID | None = Field(None)
    credit_allowed: bool | None = Field(None)
    credit_limit: Decimal | None = Field(None, ge=0)
    fuel_coefficient: float | None = Field(None, gt=0, le=5.0)
    delivery_coefficient: float | None = Field(None, gt=0, le=5.0)


class AddMemberRequest(BaseModel):
    """Добавить сотрудника в организацию по номеру телефона."""
    phone: str = Field(..., min_length=4, max_length=32)
