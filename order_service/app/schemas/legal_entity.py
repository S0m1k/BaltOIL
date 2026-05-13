import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re


class LegalEntityCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    short_name: str | None = Field(None, max_length=100)
    inn: str = Field(..., min_length=10, max_length=12)
    kpp: str | None = Field(None, min_length=9, max_length=9)
    ogrn: str | None = Field(None, min_length=13, max_length=15)

    bank_name: str | None = Field(None, max_length=255)
    bik: str | None = Field(None, min_length=9, max_length=9)
    checking_account: str | None = Field(None, min_length=20, max_length=20)
    correspondent_account: str | None = Field(None, min_length=20, max_length=20)

    legal_address: str | None = None
    actual_address: str | None = None

    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=255)

    director_name: str | None = Field(None, max_length=255)
    director_title: str | None = Field("Директор", max_length=100)

    @field_validator("inn")
    @classmethod
    def inn_digits(cls, v: str) -> str:
        if not re.fullmatch(r"\d{10}|\d{12}", v):
            raise ValueError("ИНН должен содержать 10 (юр. лицо) или 12 (ИП) цифр")
        return v

    @field_validator("bik")
    @classmethod
    def bik_digits(cls, v: str | None) -> str | None:
        if v is not None and not re.fullmatch(r"\d{9}", v):
            raise ValueError("БИК должен содержать 9 цифр")
        return v


class LegalEntityResponse(BaseModel):
    id: uuid.UUID
    name: str
    short_name: str | None
    inn: str
    kpp: str | None
    ogrn: str | None
    bank_name: str | None
    bik: str | None
    checking_account: str | None
    correspondent_account: str | None
    legal_address: str | None
    actual_address: str | None
    phone: str | None
    email: str | None
    director_name: str | None
    director_title: str | None
    effective_from: datetime
    effective_to: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


def legal_entity_to_snapshot(entity: "LegalEntityResponse | object") -> dict:
    """Преобразовать запись юр. лица в плоский dict для сохранения в Document.seller_snapshot."""
    return {
        "name": entity.name,
        "short_name": entity.short_name,
        "inn": entity.inn,
        "kpp": entity.kpp,
        "ogrn": entity.ogrn,
        "bank_name": entity.bank_name,
        "bik": entity.bik,
        "checking_account": entity.checking_account,
        "correspondent_account": entity.correspondent_account,
        "legal_address": entity.legal_address,
        "actual_address": entity.actual_address,
        "phone": entity.phone,
        "email": entity.email,
        "director_name": entity.director_name,
        "director_title": entity.director_title,
    }
