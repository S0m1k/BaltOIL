from typing import Annotated
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.core.dependencies import CurrentUser, get_request_meta
from app.core.rate_limit import limiter
from app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest
from app.schemas.user import (
    RegisterIndividualRequest, RegisterCompanyRequest, UserResponse,
)
from app.services import auth_service, user_service

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
    # Автоматически входим после регистрации
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
