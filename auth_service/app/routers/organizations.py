import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import UserRole
from app.core.dependencies import CurrentUser, require_roles
from app.schemas.organization import (
    OrganizationResponse, OrganizationMemberResponse,
    CreateOrganizationRequest, UpdateOrganizationRequest,
    UpdateOrganizationCommercialRequest, AddMemberRequest,
)
from app.services import organization_service as svc

router = APIRouter(prefix="/organizations", tags=["organizations"])

AdminOnly = Annotated[object, Depends(require_roles(UserRole.ADMIN))]
_STAFF = (UserRole.ADMIN, UserRole.MANAGER)


@router.get("", response_model=list[OrganizationResponse])
async def list_organizations(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    user_id: uuid.UUID | None = Query(None, description="Чьи организации (только staff)"),
    search: str | None = Query(None, description="Поиск по названию/ИНН (только staff, все организации)"),
):
    """Организации текущего пользователя.

    Staff: с user_id — организации этого пользователя; без user_id — все
    организации (с поиском по названию/ИНН), аналог раздела «Клиенты».
    """
    if current_user.role in _STAFF:
        if user_id:
            return await svc.list_user_organizations(db, user_id)
        return await svc.list_all_organizations(db, search)
    return await svc.list_user_organizations(db, current_user.id)


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    data: CreateOrganizationRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Создать организацию (текущий пользователь становится владельцем)."""
    return await svc.create_organization(db, current_user, data)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await svc._require_member(db, org_id, current_user)


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: uuid.UUID,
    data: UpdateOrganizationRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await svc.update_organization(db, org_id, current_user, data)


@router.patch("/{org_id}/commercial", response_model=OrganizationResponse)
async def update_commercial(
    org_id: uuid.UUID,
    data: UpdateOrganizationCommercialRequest,
    _: AdminOnly,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Тариф/кредит организации — только admin."""
    return await svc.update_commercial(db, org_id, data)


@router.delete("/{org_id}", status_code=204)
async def archive_organization(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await svc.archive_organization(db, org_id, current_user)


@router.get("/{org_id}/members", response_model=list[OrganizationMemberResponse])
async def list_members(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await svc.list_members(db, org_id, current_user)


@router.post("/{org_id}/members", response_model=OrganizationMemberResponse, status_code=201)
async def add_member(
    org_id: uuid.UUID,
    data: AddMemberRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Добавить сотрудника по телефону (owner/admin)."""
    return await svc.add_member(db, org_id, current_user, data.phone)


@router.delete("/{org_id}/members/{member_id}", status_code=204)
async def remove_member(
    org_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await svc.remove_member(db, org_id, member_id, current_user)
