import os
import uuid
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.schemas.legal_entity import LegalEntityCreate, LegalEntityResponse
from app.services import legal_entity_service

router = APIRouter(prefix="/admin/legal-entity", tags=["admin", "legal-entity"])

AdminOnly = Annotated[object, Depends(require_roles("admin"))]

# ── Факсимиле (подпись/печать продавца) — хранятся файлами, без миграции БД ────

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))
LEGAL_DIR = MEDIA_ROOT / "legal"
_ALLOWED = {"image/png": ".png", "image/jpeg": ".jpg"}
_MAX_BYTES = 2 * 1024 * 1024


async def _save_legal_image(file: UploadFile, dst_name: str) -> None:
    """Сохранить факсимиле (подпись/печать) на диск с проверкой типа и размера.

    Имя файла фиксированное (signature.png / stamp.png) независимо от реального
    типа загруженного файла — при рендере PDF mime определяется по содержимому.
    """
    if file.content_type not in _ALLOWED:
        raise HTTPException(status_code=415, detail="Только PNG или JPEG")
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 2 МБ")
    LEGAL_DIR.mkdir(parents=True, exist_ok=True)
    (LEGAL_DIR / dst_name).write_bytes(data)


@router.get("", response_model=LegalEntityResponse | None)
async def get_current(
    _: AdminOnly,
    db: AsyncSession = Depends(get_db),
):
    """Получить актуальные реквизиты юридического лица."""
    return await legal_entity_service.get_active(db)


@router.put("", response_model=LegalEntityResponse)
async def update(
    data: LegalEntityCreate,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Обновить реквизиты: создаёт новую версию, старую архивирует.

    Доступ: admin only. Каждый вызов создаёт новую запись с актуальными
    реквизитами — старые версии сохраняются для уже выпущенных документов.
    """
    if actor.role != "admin":
        from app.core.exceptions import ForbiddenError
        raise ForbiddenError("Изменять реквизиты может только администратор")
    entity = await legal_entity_service.create_version(db, data, actor)
    await db.commit()
    return entity


@router.post("", response_model=LegalEntityResponse, status_code=201)
async def create_or_update(
    data: LegalEntityCreate,
    actor: CurrentUser,
    _: AdminOnly,
    db: AsyncSession = Depends(get_db),
):
    """Создать новую версию реквизитов (текущая архивируется).

    Оставлен для обратной совместимости. Предпочтительный метод — PUT.
    """
    entity = await legal_entity_service.create_version(db, data, actor)
    await db.commit()
    return entity


@router.get("/history", response_model=list[LegalEntityResponse])
async def get_history(
    actor: CurrentUser,
    _: AdminOnly,
    db: AsyncSession = Depends(get_db),
):
    """История всех версий реквизитов (от новых к старым)."""
    return await legal_entity_service.get_history(db, actor)


@router.post("/signature", status_code=200)
async def upload_signature(
    _: AdminOnly,
    file: UploadFile = File(...),
):
    """Загрузить подпись директора (факсимиле). PNG/JPEG, до 2 МБ."""
    await _save_legal_image(file, "signature.png")
    return {"ok": True}


@router.post("/stamp", status_code=200)
async def upload_stamp(
    _: AdminOnly,
    file: UploadFile = File(...),
):
    """Загрузить печать организации (факсимиле). PNG/JPEG, до 2 МБ."""
    await _save_legal_image(file, "stamp.png")
    return {"ok": True}


@router.get("/signature")
async def get_signature(_: AdminOnly):
    path = LEGAL_DIR / "signature.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Подпись не загружена")
    return FileResponse(str(path), media_type="image/png")


@router.get("/stamp")
async def get_stamp(_: AdminOnly):
    path = LEGAL_DIR / "stamp.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Печать не загружена")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/signature")
async def delete_signature(_: AdminOnly):
    path = LEGAL_DIR / "signature.png"
    if path.exists():
        path.unlink()
    return {"ok": True}


@router.delete("/stamp")
async def delete_stamp(_: AdminOnly):
    path = LEGAL_DIR / "stamp.png"
    if path.exists():
        path.unlink()
    return {"ok": True}


@router.get("/{entity_id}", response_model=LegalEntityResponse)
async def get_version(
    entity_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Получить конкретную версию реквизитов по ID."""
    return await legal_entity_service.get_by_id(db, entity_id, actor)
