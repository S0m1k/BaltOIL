"""
Договоры поставки (Sprint 2026-07 Деплой 2).

Договор живёт на клиенте. Генерация и список — manager/admin. Скачивание —
manager/admin для любого договора, клиент — только своего.
"""
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Response, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.media import resolve_media_path
from app.core.exceptions import ForbiddenError, NotFoundError
from app.models.contract import ContractStatus
from app.services import contract_service
from app.services import document_export

router = APIRouter(tags=["contracts"])

ManagerOrAdmin = Annotated[object, Depends(require_roles("manager", "admin"))]

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))


class ContractResponse(BaseModel):
    id: uuid.UUID
    client_id: uuid.UUID
    contract_number: str
    status: ContractStatus
    signed_at: date | None
    effective_until: date | None
    file_path: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.post(
    "/clients/{client_id}/contracts",
    response_model=ContractResponse,
    status_code=201,
)
async def create_contract(
    client_id: uuid.UUID,
    actor: CurrentUser,
    _: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
    organization_id: uuid.UUID | None = Query(None, description="Организация (юрлицо) договора"),
):
    """Сформировать договор для клиента/организации (идемпотентно — вернёт активный)."""
    contract = await contract_service.create_contract(db, client_id, actor, organization_id)
    await db.commit()
    await db.refresh(contract)
    return contract


@router.get(
    "/clients/{client_id}/contracts",
    response_model=list[ContractResponse],
)
async def list_client_contracts(
    client_id: uuid.UUID,
    actor: CurrentUser,
    _: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Список договоров клиента (активные + расторгнутые/истёкшие)."""
    return await contract_service.list_contracts(db, client_id)


@router.get("/contracts/{contract_id}", response_model=ContractResponse)
async def get_contract(
    contract_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Метаданные договора. Клиент видит только свой."""
    contract = await contract_service.get_contract(db, contract_id)
    if actor.role not in ("manager", "admin") and contract.client_id != actor.id:
        raise ForbiddenError("Договор принадлежит другому клиенту")
    return contract


@router.get("/contracts/{contract_id}/export")
async def export_contract(
    contract_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Выгрузить договор в редактируемом формате (docx)."""
    contract = await contract_service.get_contract(db, contract_id)
    if actor.role not in ("manager", "admin") and contract.client_id != actor.id:
        raise ForbiddenError("Договор принадлежит другому клиенту")
    ctx = contract_service.build_contract_export_ctx(contract)
    content = document_export.contract_docx(ctx)
    filename = f"contract_{contract.contract_number.replace('/', '-')}.docx"
    return Response(
        content=content,
        media_type=document_export.DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/contracts/{contract_id}/download")
async def download_contract(
    contract_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Скачать PDF договора."""
    contract = await contract_service.get_contract(db, contract_id)
    if actor.role not in ("manager", "admin") and contract.client_id != actor.id:
        raise ForbiddenError("Договор принадлежит другому клиенту")
    if not contract.file_path:
        raise NotFoundError("PDF договора не готов")

    full_path = resolve_media_path(MEDIA_ROOT, contract.file_path)
    if not full_path.exists():
        raise NotFoundError("Файл не найден на сервере")

    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        filename=f"contract_{contract.contract_number.replace('/', '-')}.pdf",
    )
