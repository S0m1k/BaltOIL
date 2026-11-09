import uuid
from typing import Annotated
from urllib.parse import quote
from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import UserRole
from app.core.dependencies import CurrentUser, require_roles
from app.schemas.organization import (
    OrganizationResponse, OrganizationMemberResponse, OrganizationFileResponse,
    OrganizationCommentRequest,
    CreateOrganizationRequest, UpdateOrganizationRequest,
    UpdateOrganizationCommercialRequest, AddMemberRequest,
)
from app.services import organization_service as svc
from app.services import organization_file_service as file_svc

router = APIRouter(prefix="/organizations", tags=["organizations"])

AdminOnly = Annotated[object, Depends(require_roles(UserRole.ADMIN))]
_STAFF = (UserRole.ADMIN, UserRole.MANAGER)


def _for_viewer(org, viewer):
    """Заметка сотрудников (manager_comment) — только staff; клиенту поле = None.

    `model_copy` обязателен: правка самого ORM-объекта ушла бы в БД при commit.
    """
    if viewer.role in _STAFF:
        return org
    if isinstance(org, list):
        return [_for_viewer(o, viewer) for o in org]
    return OrganizationResponse.model_validate(org).model_copy(update={"manager_comment": None})


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
    return _for_viewer(await svc.list_user_organizations(db, current_user.id), current_user)


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    data: CreateOrganizationRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Создать организацию (текущий пользователь становится владельцем)."""
    return _for_viewer(await svc.create_organization(db, current_user, data), current_user)


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return _for_viewer(await svc._require_member(db, org_id, current_user), current_user)


@router.patch("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: uuid.UUID,
    data: UpdateOrganizationRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return _for_viewer(await svc.update_organization(db, org_id, current_user, data), current_user)


@router.put("/{org_id}/manager-comment", response_model=OrganizationResponse)
async def set_manager_comment(
    org_id: uuid.UUID,
    data: OrganizationCommentRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Заметка сотрудников рядом с названием организации (CRM-62) — только staff."""
    return await svc.set_manager_comment(db, org_id, current_user, data.comment)


@router.get("/{org_id}/files", response_model=list[OrganizationFileResponse])
async def list_org_files(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Файлы организации (карточка реквизитов и т. п.) — staff и участники (CRM-63)."""
    return await file_svc.list_files(db, org_id, current_user)


@router.post("/{org_id}/files", response_model=OrganizationFileResponse, status_code=201)
async def upload_org_file(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Прикрепить файл (PDF/Word/Excel до 10 МБ) — только staff."""
    # Читаем с запасом в 1 байт: превышение лимита видно без загрузки всего файла в память
    data = await file.read(file_svc.MAX_FILE_BYTES + 1)
    return await file_svc.add_file(db, org_id, current_user, file.filename or "", data)


@router.get("/{org_id}/files/{file_id}/download")
async def download_org_file(
    org_id: uuid.UUID,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    row = await file_svc.get_file_for_download(db, org_id, file_id, current_user)
    # Всегда вложением и с нашим типом — загруженное содержимое в браузере не исполняется
    return Response(
        content=row.content,
        media_type=row.content_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(row.filename)}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{org_id}/files/{file_id}", status_code=204)
async def delete_org_file(
    org_id: uuid.UUID,
    file_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await file_svc.delete_file(db, org_id, file_id, current_user)


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


@router.post("/{org_id}/members/{member_id}/make-owner", status_code=204)
async def make_owner(
    org_id: uuid.UUID,
    member_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Сменить владельца организации (только staff): выбранный участник —
    владелец, прежний — сотрудник."""
    await svc.set_owner(db, org_id, member_id, current_user)
