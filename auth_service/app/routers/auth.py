from typing import Annotated
from fastapi import APIRouter, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, get_request_meta
from app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest
from app.schemas.user import (
    RegisterIndividualRequest, RegisterCompanyRequest, UserResponse
)
from app.services import auth_service, user_service

router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/register/individual", response_model=UserResponse, status_code=201)
@limiter.limit("10/minute")
async def register_individual(
    data: RegisterIndividualRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    user = await user_service.register_individual(db, data, **meta)
    return user


@router.post("/register/company", response_model=UserResponse, status_code=201)
@limiter.limit("10/minute")
async def register_company(
    data: RegisterCompanyRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    user = await user_service.register_company(db, data, **meta)
    return user


@router.post("/login", response_model=TokenResponse)
@limiter.limit("20/minute")
async def login(
    data: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await auth_service.login(db, email=data.email, password=data.password, **meta)


@router.post("/refresh", response_model=TokenResponse)
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
