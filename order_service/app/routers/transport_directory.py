"""Справочники перевозки: /transport/bases и /transport/client-objects."""
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import NotFoundError
from app.core.media import content_disposition_attachment, resolve_media_path
from app.database import get_db
from app.schemas.transport import (
    TransportBaseCreateRequest, TransportBaseResponse, TransportBaseUpdateRequest,
    TransportClientObjectCreateRequest, TransportClientObjectResponse,
    TransportClientObjectUpdateRequest,
)
from app.services import transport_directory

router = APIRouter(prefix="/transport", tags=["transport"])

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))
CONTRACTS_SUBDIR = "transport_contracts"

#: Договор объекта — PDF или офисный документ, до 15 МБ.
_ALLOWED_CONTRACT_TYPES = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "image/png": ".png",
    "image/jpeg": ".jpg",
}
_MAX_CONTRACT_BYTES = 15 * 1024 * 1024


# ── Нефтебазы ─────────────────────────────────────────────────────────────────


@router.get("/bases", response_model=list[TransportBaseResponse])
async def list_bases(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(False),
):
    return await transport_directory.list_bases(
        db, current_user, include_inactive=include_inactive
    )


@router.post("/bases", response_model=TransportBaseResponse, status_code=201)
async def create_base(
    data: TransportBaseCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await transport_directory.create_base(db, data, current_user)


@router.patch("/bases/{base_id}", response_model=TransportBaseResponse)
async def update_base(
    base_id: uuid.UUID,
    data: TransportBaseUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await transport_directory.update_base(db, base_id, data, current_user)


@router.delete("/bases/{base_id}", status_code=204)
async def delete_base(
    base_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await transport_directory.delete_base(db, base_id, current_user)


# ── Объекты клиентов ──────────────────────────────────────────────────────────


@router.get("/client-objects", response_model=list[TransportClientObjectResponse])
async def list_client_objects(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(False),
):
    objects = await transport_directory.list_client_objects(
        db, current_user, include_inactive=include_inactive
    )
    return [transport_directory.to_response_dict(o) for o in objects]


@router.post("/client-objects", response_model=TransportClientObjectResponse, status_code=201)
async def create_client_object(
    data: TransportClientObjectCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    obj = await transport_directory.create_client_object(db, data, current_user)
    return transport_directory.to_response_dict(obj)


@router.patch("/client-objects/{object_id}", response_model=TransportClientObjectResponse)
async def update_client_object(
    object_id: uuid.UUID,
    data: TransportClientObjectUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    obj = await transport_directory.update_client_object(db, object_id, data, current_user)
    return transport_directory.to_response_dict(obj)


@router.delete("/client-objects/{object_id}", status_code=204)
async def delete_client_object(
    object_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await transport_directory.delete_client_object(db, object_id, current_user)


@router.post(
    "/client-objects/{object_id}/contract",
    response_model=TransportClientObjectResponse,
)
async def upload_contract(
    object_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Прикрепить договор к объекту клиента (пока — просто загрузка файла)."""
    ext = _ALLOWED_CONTRACT_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(
            status_code=415, detail="Допустимы PDF, DOC/DOCX, PNG или JPEG"
        )
    data = await file.read()
    if len(data) > _MAX_CONTRACT_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 15 МБ")

    # Имя файла на диске генерируем сами: пользовательское имя хранится в БД
    # и наружу отдаётся только в Content-Disposition — path traversal исключён.
    rel_path = f"{CONTRACTS_SUBDIR}/{object_id}{ext}"
    dst = MEDIA_ROOT / rel_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)

    obj = await transport_directory.set_contract_file(
        db, object_id, rel_path, file.filename or f"Договор{ext}", current_user
    )
    return transport_directory.to_response_dict(obj)


@router.get("/client-objects/{object_id}/contract")
async def download_contract(
    object_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    obj = await transport_directory.get_client_object(db, object_id, current_user)
    if not obj.contract_file_path:
        raise NotFoundError("Договор не загружен")
    path = resolve_media_path(MEDIA_ROOT, obj.contract_file_path)
    if not path.exists():
        raise NotFoundError("Файл договора не найден на сервере")
    return FileResponse(
        str(path),
        headers={
            "Content-Disposition": content_disposition_attachment(
                obj.contract_file_name or path.name
            )
        },
    )
