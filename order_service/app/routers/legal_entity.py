import uuid
from typing import Annotated
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.schemas.legal_entity import LegalEntityCreate, LegalEntityResponse
from app.services import legal_entity_service

router = APIRouter(prefix="/admin/legal-entity", tags=["admin", "legal-entity"])

AdminOnly = Annotated[object, Depends(require_roles("admin"))]


@router.get("", response_model=LegalEntityResponse | None)
async def get_current(
    _: AdminOnly,
    db: AsyncSession = Depends(get_db),
):
    """Получить актуальные реквизиты юридического лица."""
    return await legal_entity_service.get_active(db)


@router.post("", response_model=LegalEntityResponse, status_code=201)
async def create_or_update(
    data: LegalEntityCreate,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Создать новую версию реквизитов (текущая архивируется).

    Каждый вызов создаёт новую запись с актуальными реквизитами.
    Старая версия сохраняется в истории — уже выпущенные документы остаются корректными.
    """
    entity = await legal_entity_service.create_version(db, data, actor)
    await db.commit()
    return entity


@router.get("/history", response_model=list[LegalEntityResponse])
async def get_history(
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """История всех версий реквизитов (от новых к старым)."""
    return await legal_entity_service.get_history(db, actor)


@router.get("/{entity_id}", response_model=LegalEntityResponse)
async def get_version(
    entity_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Получить конкретную версию реквизитов по ID."""
    return await legal_entity_service.get_by_id(db, entity_id, actor)
