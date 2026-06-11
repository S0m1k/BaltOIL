"""Internal endpoints for service-to-service communication.

These routes are NOT exposed through nginx — they are only accessible
on the Docker internal network. Auth is done via X-Internal-Secret header
(HMAC-safe comparison, same secret used by delivery/notification services).
"""
import hmac
import uuid
from decimal import Decimal
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.config import get_settings
from app.core.phone import normalize_phone, normalized_phone_column
from app.database import get_db
from app.models.user import User, UserRole
from app.models.client_profile import ClientProfile

router = APIRouter(prefix="/internal", tags=["internal"])
settings = get_settings()


def _require_internal(
    x_internal_secret: Annotated[str, Header(alias="X-Internal-Secret")],
) -> None:
    if not hmac.compare_digest(x_internal_secret, settings.internal_api_secret):
        raise HTTPException(status_code=403, detail="Invalid internal secret")


class ClientContextResponse(BaseModel):
    user_id: uuid.UUID
    client_type: str           # "individual" | "company"
    credit_allowed: bool
    tariff_id: uuid.UUID | None  # None → order_service uses default tariff
    credit_limit: Decimal | None  # None → no credit limit configured
    fuel_coefficient: float     # multiplier for fuel price (default 1.0)
    delivery_coefficient: float  # multiplier for delivery cost (default 1.0)


@router.get(
    "/clients/{client_id}/context",
    response_model=ClientContextResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_client_context(
    client_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientContextResponse:
    """Return client_type, credit_allowed, tariff_id for order_service pricing checks."""
    result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == client_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Client profile not found")

    return ClientContextResponse(
        user_id=client_id,
        client_type=profile.client_type.value,
        credit_allowed=profile.credit_allowed,
        tariff_id=profile.tariff_id,
        credit_limit=profile.credit_limit,
        fuel_coefficient=float(profile.fuel_coefficient),
        delivery_coefficient=float(profile.delivery_coefficient),
    )


class BuyerSnapshotResponse(BaseModel):
    """Снимок реквизитов клиента для подстановки в счёт/ТТН/УПД."""
    name: str             # юр. название или ФИО
    inn: str | None
    kpp: str | None
    ogrn: str | None
    legal_address: str | None
    director_name: str | None
    delivery_address: str | None


@router.get(
    "/clients/{client_id}/buyer-snapshot",
    response_model=BuyerSnapshotResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_buyer_snapshot(
    client_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BuyerSnapshotResponse:
    """Реквизиты клиента для документов (счёт/ТТН/УПД)."""
    user_result = await db.execute(select(User).where(User.id == client_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    profile_result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == client_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile and profile.client_type.value == "company":
        return BuyerSnapshotResponse(
            name=profile.company_name or user.full_name,
            inn=profile.inn,
            kpp=profile.kpp,
            ogrn=profile.ogrn,
            legal_address=profile.legal_address or profile.delivery_address,
            director_name=profile.director_name,
            delivery_address=profile.delivery_address,
        )
    return BuyerSnapshotResponse(
        name=user.full_name,
        inn=None, kpp=None, ogrn=None,
        legal_address=profile.delivery_address if profile else None,
        director_name=None,
        delivery_address=profile.delivery_address if profile else None,
    )


class EmailTargetResponse(BaseModel):
    email: str | None


@router.get(
    "/users/{user_id}/email-target",
    response_model=EmailTargetResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_user_email_target(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EmailTargetResponse:
    """Return billing_email (from ClientProfile) or fallback to User.email.

    Used by notification_service to find the delivery address for email notifications.
    Returns {"email": null} if the user does not exist.
    """
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        return EmailTargetResponse(email=None)

    profile_result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if profile and profile.billing_email:
        return EmailTargetResponse(email=profile.billing_email)

    return EmailTargetResponse(email=user.email)


@router.get(
    "/users-by-role",
    response_model=list[uuid.UUID],
    dependencies=[Depends(_require_internal)],
)
async def get_users_by_role(
    roles: str,  # comma-separated, e.g. "manager,admin"
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[uuid.UUID]:
    """Return user IDs for all active users with the given roles (for notification fanout)."""
    role_list = [r.strip() for r in roles.split(",") if r.strip()]
    result = await db.execute(
        select(User.id).where(
            User.role.in_(role_list),
            User.is_active == True,  # noqa: E712
        )
    )
    return [row[0] for row in result.all()]


class LegalProfileResponse(BaseModel):
    """Полные реквизиты клиента-юрлица для договора (включая банк)."""
    name: str                       # company_name или full_name
    inn: str | None
    kpp: str | None
    ogrn: str | None
    okpo: str | None
    legal_address: str | None
    bank_name: str | None
    bik: str | None
    checking_account: str | None    # р/с
    correspondent_account: str | None  # к/с
    director_name: str | None
    phone: str | None
    email: str | None


@router.get(
    "/users/{user_id}/legal-profile",
    response_model=LegalProfileResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_user_legal_profile(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LegalProfileResponse:
    """Реквизиты клиента-юрлица для генерации договора.

    404 если клиент физлицо или у профиля не заполнены юр-данные (нет ИНН) —
    вызывающая сторона трактует как «нельзя сформировать договор».
    """
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    profile_result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == user_id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or profile.client_type.value != "company" or not profile.inn:
        raise HTTPException(status_code=404, detail="Client has no legal profile")

    return LegalProfileResponse(
        name=profile.company_name or user.full_name,
        inn=profile.inn,
        kpp=profile.kpp,
        ogrn=profile.ogrn,
        okpo=profile.okpo,
        legal_address=profile.legal_address or profile.delivery_address,
        bank_name=profile.bank_name,
        bik=profile.bik,
        checking_account=profile.bank_account,
        correspondent_account=profile.correspondent_account,
        director_name=profile.director_name,
        phone=None,
        email=profile.billing_email or user.email,
    )


class DriverProfileResponse(BaseModel):
    """ФИО + паспорт пользователя (водителя) для доверенности М-2."""
    full_name: str
    passport_series: str | None
    passport_number: str | None
    passport_issued_by: str | None
    passport_issued_at: str | None  # ISO-дата или null


@router.get(
    "/users/{user_id}/profile",
    response_model=DriverProfileResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_user_profile(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DriverProfileResponse:
    """ФИО и паспортные данные пользователя (для рендера доверенности)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return DriverProfileResponse(
        full_name=user.full_name,
        passport_series=user.passport_series,
        passport_number=user.passport_number,
        passport_issued_by=user.passport_issued_by,
        passport_issued_at=user.passport_issued_at.isoformat() if user.passport_issued_at else None,
    )


class ContactResponse(BaseModel):
    """Лёгкая карточка пользователя для чата: имя, роль, телефон."""
    id: uuid.UUID
    full_name: str
    role: str
    phone: str | None
    # Блокировка мессенджера (правки 2026-06-11): chat_service запрещает
    # заблокированному клиенту писать и находиться по номеру.
    messenger_blocked: bool = False
    client_type: str | None = None  # "individual" | "company" | None (не клиент)


@router.get(
    "/users/by-phone",
    response_model=ContactResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_user_by_phone(
    db: Annotated[AsyncSession, Depends(get_db)],
    phone: str = Query(..., min_length=4, max_length=32),
) -> ContactResponse:
    """Найти активного пользователя по номеру телефона (для «начать чат по номеру»).

    Сравнение по последним 10 цифрам — формат хранения телефона свободный
    (+7 999…, 8999…, с пробелами). 404 если не найден.
    """
    norm = normalize_phone(phone)
    if len(norm) < 10:
        raise HTTPException(status_code=404, detail="User not found")
    result = await db.execute(
        select(User).where(
            User.phone.isnot(None),
            normalized_phone_column(User.phone) == norm,
            User.is_active == True,  # noqa: E712
            User.is_archived == False,  # noqa: E712
        )
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    profile_res = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == user.id)
    )
    profile = profile_res.scalar_one_or_none()
    return ContactResponse(
        id=user.id,
        full_name=user.full_name,
        role=user.role.value,
        phone=user.phone,
        messenger_blocked=bool(profile.messenger_blocked) if profile else False,
        client_type=profile.client_type.value if profile else None,
    )


@router.get(
    "/users/contacts",
    response_model=list[ContactResponse],
    dependencies=[Depends(_require_internal)],
)
async def get_contacts(
    db: Annotated[AsyncSession, Depends(get_db)],
    ids: str = Query(..., description="comma-separated user UUIDs"),
) -> list[ContactResponse]:
    """Батч-резолв id → {full_name, role, phone} для отображения участников чата."""
    id_list: list[uuid.UUID] = []
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            id_list.append(uuid.UUID(raw))
        except ValueError:
            continue
    if not id_list:
        return []
    result = await db.execute(select(User).where(User.id.in_(id_list)))
    users = list(result.scalars().all())
    profiles_res = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id.in_([u.id for u in users]))
    )
    profiles = {p.user_id: p for p in profiles_res.scalars().all()}
    return [
        ContactResponse(
            id=u.id,
            full_name=u.full_name,
            role=u.role.value,
            phone=u.phone,
            messenger_blocked=bool(profiles[u.id].messenger_blocked) if u.id in profiles else False,
            client_type=profiles[u.id].client_type.value if u.id in profiles else None,
        )
        for u in users
    ]


@router.get(
    "/users/admin-recipients",
    response_model=list[str],
    dependencies=[Depends(_require_internal)],
)
async def get_admin_recipients(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[str]:
    """Email-ы всех активных admin+manager — для рассылки уведомлений о договоре."""
    result = await db.execute(
        select(User.email).where(
            User.role.in_(["admin", "manager"]),
            User.is_active == True,  # noqa: E712
            User.email.isnot(None),
        )
    )
    return [row[0] for row in result.all() if row[0]]
