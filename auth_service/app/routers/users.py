import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import UserRole
from app.core.dependencies import CurrentUser, require_roles, get_request_meta
from app.core.rate_limit import limiter
from app.schemas.auth import ChangePasswordRequest
from app.schemas.user import UserResponse, UserShortResponse, UserDirectoryEntry, CreateUserRequest, UpdateUserRequest
from app.schemas.client_profile import ClientProfileResponse, UpdateClientProfileRequest, UpdateClientTariffRequest
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

AdminOnly = Annotated[object, Depends(require_roles(UserRole.ADMIN))]
AdminOrManager = Annotated[object, Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))]


@router.get("", response_model=list[UserShortResponse])
async def list_users(
    _: AdminOrManager,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: UserRole | None = Query(None),
    include_inactive: bool = Query(False),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    client_number: int | None = Query(None, description="Найти клиента по короткому номеру"),
):
    users = await user_service.list_users(
        db,
        role=role,
        include_inactive=include_inactive,
        offset=offset,
        limit=limit,
        client_number=client_number,
    )
    result = []
    for u in users:
        entry = UserShortResponse.model_validate(u)
        if hasattr(u, "client_profile") and u.client_profile:
            entry.client_number = u.client_profile.client_number
        result.append(entry)
    return result


@router.get("/directory", response_model=list[UserDirectoryEntry])
async def users_directory(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    role: UserRole | None = Query(None, description="Фильтр по роли"),
    limit: int = Query(500, ge=1, le=1000),
):
    """Адресная книга: id + ФИО + роль активных пользователей.
    Доступна любому залогиненному — нужна чату для:
      • резолва UUID участников в имена при просмотре участников диалога
      • подсказок при создании нового внутреннего чата (водитель тоже выбирает)
    Не возвращает email/телефон и архивированных/деактивированных.
    """
    _ = current_user  # explicit dependency: only authenticated requests allowed
    return await user_service.list_users(
        db, role=role, include_inactive=False, offset=0, limit=limit
    )


@router.post("", response_model=UserResponse, status_code=201)
async def create_user(
    data: CreateUserRequest,
    current_user: CurrentUser,
    _: AdminOnly,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await user_service.create_user_by_admin(
        db, data, actor_id=current_user.id, ip_address=meta["ip_address"]
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    # Clients can only see themselves
    if current_user.role == UserRole.CLIENT and current_user.id != user_id:
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError()
    return await user_service.get_user_by_id(db, user_id)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    data: UpdateUserRequest,
    current_user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await user_service.update_user(
        db, user_id, data, actor=current_user, ip_address=meta["ip_address"]
    )


@router.delete("/{user_id}", status_code=204)
async def archive_user(
    user_id: uuid.UUID,
    _: AdminOnly,
    current_user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    await user_service.archive_user(
        db, user_id, actor=current_user, ip_address=meta["ip_address"]
    )


@router.patch("/{user_id}/profile", response_model=ClientProfileResponse)
@limiter.limit("30/minute")
async def update_client_profile(
    user_id: uuid.UUID,
    data: UpdateClientProfileRequest,
    current_user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    return await user_service.update_client_profile(
        db, user_id, data, actor=current_user, ip_address=meta["ip_address"]
    )


@router.patch("/{user_id}/tariff", response_model=ClientProfileResponse)
async def update_client_tariff(
    user_id: uuid.UUID,
    data: UpdateClientTariffRequest,
    current_user: CurrentUser,
    _: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await user_service.update_client_tariff(
        db, user_id, data, actor=current_user
    )



@router.post("/me/change-password", status_code=204)
async def change_password(
    data: ChangePasswordRequest,
    current_user: CurrentUser,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    meta = get_request_meta(request)
    await user_service.change_password(
        db,
        actor=current_user,
        current_password=data.current_password,
        new_password=data.new_password,
        ip_address=meta["ip_address"],
    )
