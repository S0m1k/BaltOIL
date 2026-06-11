from typing import Annotated
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.core.dependencies import CurrentUser, get_request_meta
from app.core.rate_limit import limiter
from app.core.phone import normalize_phone, normalized_phone_column
from app.core.security import hash_password
from app.core.exceptions import AuthError
from app.models.user import User
from app.schemas.auth import (
    LoginRequest, TokenResponse, RefreshRequest,
    RequestCodeRequest, VerifyCodeRequest, PasswordResetRequest,
)
from app.schemas.user import (
    RegisterIndividualRequest, RegisterCompanyRequest, UserResponse,
)
from app.services import auth_service, user_service, otp_service, sms_client
from app.services.auth_service import _issue_tokens_for_user
from app.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register/individual", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register_individual(
    data: RegisterIndividualRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    await user_service.register_individual(db, data, **meta)
    # Автоматически входим после регистрации — по телефону (email может быть пустым)
    return await auth_service.login(db, identifier=data.phone, password=data.password, **meta)


@router.post("/register/company", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register_company(
    data: RegisterCompanyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    await user_service.register_company(db, data, **meta)
    # Автоматически входим после регистрации — email теперь необязателен
    # (правки 2026-06-11), без него входим по телефону.
    return await auth_service.login(
        db, identifier=data.email or data.phone, password=data.password, **meta
    )


@router.post("/login", response_model=TokenResponse)
@limiter.limit("30/minute")
async def login(
    data: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await auth_service.login(db, identifier=data.identifier, password=data.password, **meta)


# ── SMS-code login / password reset ────────────────────────────
# OTP-коды живут в auth_service (Redis, otp_service). notification_service —
# тупой отправитель. Телефон нормализуется (последние 10 цифр), чтобы код,
# запрошенный в одном формате, подтверждался в любом.
_GENERIC_CODE_MSG = {"detail": "Если номер зарегистрирован, код будет отправлен в SMS"}


async def _find_active_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    norm = normalize_phone(phone)
    if len(norm) != 10:
        return None
    result = await db.execute(
        select(User).where(
            User.phone.isnot(None),
            normalized_phone_column(User.phone) == norm,
            User.is_active == True,      # noqa: E712
            User.is_archived == False,   # noqa: E712
        )
    )
    return result.scalars().first()


@router.post("/login/request-code", status_code=200)
@limiter.limit("10/minute")
async def login_request_code(
    data: RequestCodeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Запросить SMS-код для входа. Всегда 200 — защита от энумерации номеров."""
    user = await _find_active_user_by_phone(db, data.phone)
    if user:
        norm = normalize_phone(data.phone)
        code = await otp_service.issue_code("login", norm)
        if code:
            await sms_client.send_otp(data.phone, code, "login")
    return _GENERIC_CODE_MSG


@router.post("/login/verify-code", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login_verify_code(
    data: VerifyCodeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Подтвердить SMS-код входа и выдать токены."""
    meta = get_request_meta(request)
    norm = normalize_phone(data.phone)
    if not await otp_service.verify_code("login", norm, data.code):
        raise AuthError("Неверный или просроченный код")
    user = await _find_active_user_by_phone(db, data.phone)
    if not user:
        raise AuthError("Неверный или просроченный код")
    return await _issue_tokens_for_user(db, user, **meta)


@router.post("/password/request-code", status_code=200)
@limiter.limit("10/minute")
async def password_request_code(
    data: RequestCodeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Запросить SMS-код для сброса пароля. Всегда 200."""
    user = await _find_active_user_by_phone(db, data.phone)
    if user:
        norm = normalize_phone(data.phone)
        code = await otp_service.issue_code("reset", norm)
        if code:
            await sms_client.send_otp(data.phone, code, "reset")
    return _GENERIC_CODE_MSG


@router.post("/password/reset", status_code=200)
@limiter.limit("10/minute")
async def password_reset(
    data: PasswordResetRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Проверить SMS-код сброса, установить новый пароль, отозвать все сессии."""
    meta = get_request_meta(request)
    norm = normalize_phone(data.phone)
    if not await otp_service.verify_code("reset", norm, data.code):
        raise AuthError("Неверный или просроченный код")
    user = await _find_active_user_by_phone(db, data.phone)
    if not user:
        raise AuthError("Неверный или просроченный код")

    user.hashed_password = hash_password(data.new_password)
    await auth_service.logout_all(db, user_id=user.id)
    await log_action(
        db,
        action="user.password_reset_sms",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"phone": data.phone},
        ip_address=meta.get("ip_address"),
        user_agent=meta.get("user_agent"),
    )
    return {"detail": "Пароль успешно изменён"}


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("60/minute")
async def refresh(
    data: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await auth_service.refresh_tokens(
        db, raw_refresh_token=data.refresh_token, **meta
    )


@router.post("/logout", status_code=204)
async def logout(
    data: RefreshRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await auth_service.logout(
        db, raw_refresh_token=data.refresh_token, actor_id=current_user.id
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser):
    return current_user


@router.get("/lookup/inn")
@limiter.limit("5/minute")
async def lookup_inn(
    request: Request,
    inn: str = Query(..., min_length=10, max_length=12),
):
    """Поиск организации по ИНН через DaData. Без авторизации.

    Возвращает {found, data: {company_name, kpp, ogrn, legal_address,
        okved, okpo, okato, fns_status, director_name}} или {found: false}.
    Если DADATA_API_KEY не задан — возвращает found=false (регистрация вручную).
    """
    from app.services.dadata_service import lookup_by_inn
    api_key = get_settings().dadata_api_key
    if not api_key:
        return {"found": False, "data": None}
    result = await lookup_by_inn(inn, api_key)
    if result:
        return {"found": True, "data": result}
    return {"found": False, "data": None}


@router.get("/lookup/bik")
@limiter.limit("10/minute")
async def lookup_bik(
    request: Request,
    bik: str = Query(..., min_length=9, max_length=9, pattern=r"^\d{9}$"),
):
    """Поиск банка по БИК через DaData. Без авторизации.

    Возвращает {found, data: {bank_name, correspondent_account, swift,
        bank_status, bank_address}} или {found: false}.
    Если DADATA_API_KEY не задан — found=false; никаких 500 наружу.
    """
    from app.services.dadata_service import lookup_by_bik
    api_key = get_settings().dadata_api_key
    if not api_key:
        return {"found": False, "data": None, "error": "service_unavailable"}
    result = await lookup_by_bik(bik, api_key)
    if result:
        return {"found": True, "data": result}
    return {"found": False, "data": None}
