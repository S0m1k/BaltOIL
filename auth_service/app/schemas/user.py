import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator
from app.models.user import UserRole
from app.models.client_profile import ClientType
from .client_profile import ClientProfileResponse


# --- Responses ---

class UserShortResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    phone: str | None
    full_name: str
    role: UserRole
    is_active: bool
    is_archived: bool
    archived_at: datetime | None
    client_profile: ClientProfileResponse | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Registration (public) ---

class RegisterIndividualRequest(BaseModel):
    """Регистрация физического лица."""
    email: EmailStr
    phone: str
    password: str
    full_name: str
    delivery_address: str | None = None
    passport_series: str | None = None
    passport_number: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        return v


class RegisterCompanyRequest(BaseModel):
    """Регистрация юридического лица."""
    email: EmailStr
    phone: str
    password: str
    full_name: str           # ФИО контактного лица
    company_name: str
    inn: str
    kpp: str | None = None
    legal_address: str
    delivery_address: str | None = None
    bank_account: str | None = None
    bank_name: str | None = None
    bik: str | None = None
    correspondent_account: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
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
    """Создание пользователя администратором (менеджер, водитель, клиент)."""
    email: EmailStr
    phone: str | None = None
    password: str
    full_name: str
    role: UserRole

    # If role == CLIENT, client_type is required
    client_type: ClientType | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Пароль должен быть не менее 8 символов")
        return v


class UpdateUserRequest(BaseModel):
    email: EmailStr | None = None
    phone: str | None = None
    full_name: str | None = None
    is_active: bool | None = None
    # Role change only by admin — validated at service level
    role: UserRole | None = None
