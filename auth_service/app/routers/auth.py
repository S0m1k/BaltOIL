from typing import Annotated
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.config import get_settings
from app.core.dependencies import CurrentUser, get_request_meta
from app.core.rate_limit import limiter
from app.schemas.auth import (
    LoginRequest, TokenResponse, RefreshRequest,
    RequestCodeRequest, VerifyCodeRequest, PasswordResetRequest,
)
from app.schemas.user import (
    RegisterIndividualRequest, RegisterCompanyRequest, UserResponse,
)
from app.services import auth_service, user_service
from app.services import otp_service, sms_client
from app.models.user import User
from app.core.security import hash_password
from app.core.exceptions import AuthError
from app.services.auth_service import _issue_tokens_for_user
from app.services.audit_service import log_action

router = APIRouter(prefix="/auth", tags=["auth"])

_GENERIC_CODE_MSG = {"detail": "Если номер зарегистрирован, код будет отправлен в SMS"}


@router.post("/register/individual", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register_individual(
    data: RegisterIndividualRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    user = await user_service.register_individual(db, data, **meta)
    # Login after registration: use phone if email was omitted
    identifier = data.email or data.phone
    return await auth_service.login(db, identifier=identifier, password=data.password, **meta)


@router.post("/register/company", response_model=TokenResponse, status_code=201)
@limiter.limit("5/minute")
async def register_company(
    data: RegisterCompanyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    await user_service.register_company(db, data, **meta)
    # Companies always have email
    return await auth_service.login(db, identifier=data.email, password=data.password, **meta)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("30/minute")
async def login(
    data: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await auth_service.login(db, identifier=data.identifier, password=data.password, **meta)


# ── SMS-code login ─────────────────────────────────────────────

@router.post("/login/request-code", status_code=200)
@limiter.limit("10/minute")
async def login_request_code(
    data: RequestCodeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Request an SMS login code. Always returns 200 regardless of whether the
    phone is registered — prevents user enumeration."""
    result = await db.execute(select(User).where(User.phone == data.phone))
    user = result.scalar_one_or_none()

    if user and user.is_active and not user.is_archived:
        code = await otp_service.issue_code("login", data.phone)
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
    """Verify an SMS login code. Issues tokens on success."""
    meta = get_request_meta(request)
    ok = await otp_service.verify_code("login", data.phone, data.code)
    if not ok:
        raise AuthError("Неверный или просроченный код")

    result = await db.execute(
        select(User).where(User.phone == data.phone, User.is_active == True, User.is_archived == False)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise AuthError("Неверный или просроченный код")

    return await _issue_tokens_for_user(db, user, **meta)


# ── SMS-code password reset ────────────────────────────────────

@router.post("/password/request-code", status_code=200)
@limiter.limit("10/minute")
async def password_request_code(
    data: RequestCodeRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Request an SMS password-reset code. Always 200 to prevent enumeration."""
    result = await db.execute(select(User).where(User.phone == data.phone))
    user = result.scalar_one_or_none()

    if user and user.is_active and not user.is_archived:
        code = await otp_service.issue_code("reset", data.phone)
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
    """Verify SMS reset code and set a new password. Revokes all existing sessions."""
    meta = get_request_meta(request)
    ok = await otp_service.verify_code("reset", data.phone, data.code)
    if not ok:
        raise AuthError("Неверный или просроченный код")

    result = await db.execute(
        select(User).where(User.phone == data.phone, User.is_active == True, User.is_archived == False)  # noqa: E712
    )
    user = result.scalar_one_or_none()
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
