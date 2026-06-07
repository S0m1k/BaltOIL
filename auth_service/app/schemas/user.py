import uuid
from datetime import datetime, date
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from app.models.user import UserRole
from app.models.client_profile import ClientType
from .client_profile import ClientProfileResponse


# --- Responses ---

class UserShortResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    phone: str | None
    full_name: str
    role: UserRole
    is_active: bool
    client_number: int | None = None  # set for CLIENT role, None for staff

    model_config = {"from_attributes": True}


class UserDirectoryEntry(BaseModel):
    """Минимальная информация о пользователе для разрешения id → имя в чатах.
    Без email/телефона — безопасно отдавать любому залогиненному."""
    id: uuid.UUID
    full_name: str
    role: UserRole

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str | None
    phone: str | None
    full_name: str
    role: UserRole
    is_active: bool
    is_archived: bool
    archived_at: datetime | None
    passport_series: str | None = None
    passport_number: str | None = None
    passport_issued_by: str | None = None
    passport_issued_at: date | None = None
    client_profile: ClientProfileResponse | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Registration (public) ---

class RegisterIndividualRequest(BaseModel):
    """Регистрация физического лица: телефон + пароль + ФИО.

    email опционален — клиент заполняет его позже в личном кабинете.
    """
    phone: str = Field(..., min_length=4, max_length=32)
    password: str
    full_name: str = Field(..., min_length=1)
    email: EmailStr | None = None
    delivery_address: str | None = None
    passport_series: str | None = None
    passport_number: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c.isalpha() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну букву")
        return v


class RegisterCompanyRequest(BaseModel):
    """Регистрация юридического лица.

    Минимум, что собираем руками: email/password/phone/full_name (контактное лицо),
    inn (для лукапа в ЕГРЮЛ), bik+bank_account (для лукапа банка + наш расчётный).
    Остальное (company_name, kpp, ogrn, legal_address, bank_name, correspondent_account,
    director_name, okved/okpo/okato) — автозаполняется из DaData при регистрации.
    Если DaData недоступна, поля можно прислать вручную.
    """
    email: EmailStr
    phone: str
    password: str
    full_name: str           # ФИО контактного лица

    inn: str
    # bik+bank_account — нужно для регистрации; bik используется для bank lookup,
    # bank_account (р/с) клиент вводит сам — DaData его не знает.
    bik: str | None = None
    bank_account: str | None = None

    # Всё ниже — опционально: либо приедет из DaData, либо клиент введёт вручную.
    company_name: str | None = None
    kpp: str | None = None
    legal_address: str | None = None
    delivery_address: str | None = None
    bank_name: str | None = None
    correspondent_account: str | None = None
    billing_email: EmailStr | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c.isalpha() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну букву")
        return v

    @field_validator("inn")
    @classmethod
    def inn_length(cls, v: str) -> str:
        if len(v) not in (10, 12):
            raise ValueError("ИНН должен содержать 10 или 12 цифр")
        if not v.isdigit():
            raise ValueError("ИНН должен содержать только цифры")
        return v


# --- Admin: create any user ---

class CreateUserRequest(BaseModel):
    """Создание пользователя администратором (менеджер, водитель, клиент).

    email опционален (сотрудника/клиента можно завести по телефону), но хотя бы
    одно из email/phone должно быть задано — иначе не по чему входить.
    """
    email: EmailStr | None = None
    phone: str | None = None
    password: str
    full_name: str
    role: UserRole

    # If role == CLIENT, client_type is required
    client_type: ClientType | None = None

    @model_validator(mode="after")
    def _need_login(self):
        if not (self.email or self.phone):
            raise ValueError("Укажите телефон или email")
        return self

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        if not any(c.isdigit() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну цифру")
        if not any(c.isalpha() for c in v):
            raise ValueError("Пароль должен содержать хотя бы одну букву")
        return v


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    # Role change only by admin — validated at service level
    role: UserRole | None = None
    # Паспортные данные водителя (для доверенности М-2)
    passport_series: str | None = None
    passport_number: str | None = None
    passport_issued_by: str | None = None
    passport_issued_at: date | None = None


class ClientExportRequest(BaseModel):
    client_ids: list[uuid.UUID] = Field(..., max_length=1000)
