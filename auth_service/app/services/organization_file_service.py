"""Файлы организации — карточка реквизитов Word/PDF/Excel (CRM-63).

Загружают и удаляют сотрудники BaltOIL; смотреть и скачивать могут сотрудники и
участники самой организации. Содержимое хранится в БД (см. OrganizationFile).

Тип файла определяем по расширению ИЗ СПИСКА и сверяем с «магическими» байтами:
имя и Content-Type, пришедшие от клиента, доверия не заслуживают, а отдаём файл
всегда как вложение с нашим типом — чтобы загруженный html/svg не исполнился
в браузере (stored XSS).
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.exceptions import ValidationError, ForbiddenError, NotFoundError
from app.models.organization import Organization
from app.models.organization_file import OrganizationFile
from app.models.user import User, UserRole
from app.services import organization_service

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_FILES_PER_ORG = 20

_OLE = b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"  # старые .doc/.xls
_ZIP = b"PK\x03\x04"                          # .docx/.xlsx


@dataclass(frozen=True)
class _FileKind:
    content_type: str
    magic: tuple[bytes, ...]


#: расширение → допустимый тип и сигнатуры начала файла
ALLOWED_KINDS: dict[str, _FileKind] = {
    "pdf": _FileKind("application/pdf", (b"%PDF-",)),
    "doc": _FileKind("application/msword", (_OLE,)),
    "docx": _FileKind(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document", (_ZIP,)
    ),
    "xls": _FileKind("application/vnd.ms-excel", (_OLE,)),
    "xlsx": _FileKind(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", (_ZIP,)
    ),
}

_UNSAFE_NAME_CHARS = re.compile(r'[\x00-\x1f\\/:*?"<>|]+')


def clean_filename(raw: str | None) -> str:
    """Имя файла без пути и служебных символов, не длиннее 255 знаков."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_NAME_CHARS.sub("_", name).strip(" .")
    return name[:255]


def validate_upload(filename: str, data: bytes) -> tuple[str, str]:
    """Проверить файл; вернуть (очищенное имя, наш content-type)."""
    name = clean_filename(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    kind = ALLOWED_KINDS.get(ext)
    if kind is None:
        raise ValidationError("Допустимы файлы PDF, Word (doc, docx) и Excel (xls, xlsx)")
    if not data:
        raise ValidationError("Файл пустой")
    if len(data) > MAX_FILE_BYTES:
        raise ValidationError(f"Файл больше {MAX_FILE_BYTES // (1024 * 1024)} МБ")
    if not any(data.startswith(sig) for sig in kind.magic):
        raise ValidationError("Содержимое файла не соответствует его расширению")
    return name, kind.content_type


def _require_staff(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.MANAGER):
        raise ForbiddenError("Файлы организации загружает и удаляет только сотрудник")


async def list_files(db: AsyncSession, org_id: uuid.UUID, actor: User) -> list[OrganizationFile]:
    await organization_service._require_member(db, org_id, actor)
    res = await db.execute(
        select(OrganizationFile)
        .where(OrganizationFile.organization_id == org_id)
        .order_by(OrganizationFile.created_at.desc())
    )
    return list(res.scalars().all())


async def add_file(
    db: AsyncSession, org_id: uuid.UUID, actor: User, filename: str, data: bytes
) -> OrganizationFile:
    _require_staff(actor)
    org = await db.get(Organization, org_id)
    if org is None:
        raise NotFoundError("Организация не найдена")
    name, content_type = validate_upload(filename, data)

    existing = await db.execute(
        select(OrganizationFile.id).where(OrganizationFile.organization_id == org_id)
    )
    if len(existing.all()) >= MAX_FILES_PER_ORG:
        raise ValidationError(f"К организации можно прикрепить не больше {MAX_FILES_PER_ORG} файлов")

    row = OrganizationFile(
        organization_id=org_id,
        filename=name,
        content_type=content_type,
        size=len(data),
        content=data,
        uploaded_by_id=actor.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get_file(
    db: AsyncSession, org_id: uuid.UUID, file_id: uuid.UUID, *, with_content: bool = False
) -> OrganizationFile:
    stmt = select(OrganizationFile).where(
        OrganizationFile.id == file_id, OrganizationFile.organization_id == org_id
    )
    if with_content:
        # content — deferred-колонка: без явной подгрузки обращение к ней из async-кода
        # даёт MissingGreenlet (ленивая загрузка вне greenlet'а)
        stmt = stmt.options(undefer(OrganizationFile.content)).execution_options(populate_existing=True)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise NotFoundError("Файл не найден")
    return row


async def get_file_for_download(
    db: AsyncSession, org_id: uuid.UUID, file_id: uuid.UUID, actor: User
) -> OrganizationFile:
    await organization_service._require_member(db, org_id, actor)
    return await _get_file(db, org_id, file_id, with_content=True)


async def delete_file(
    db: AsyncSession, org_id: uuid.UUID, file_id: uuid.UUID, actor: User
) -> None:
    _require_staff(actor)
    row = await _get_file(db, org_id, file_id)
    await db.delete(row)
    await db.commit()
