import json
import os
import re
import uuid
import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.core.dependencies import get_current_user, TokenUser
from app.core.redis_dep import get_redis
from app.core.exceptions import ForbiddenError
from app.schemas.conversation import (
    ConversationResponse, ConversationListResponse, EnsureClientManagerRequest,
)
from app.schemas.message import MessageResponse, SendMessageRequest
from app.services import conversation_service, message_service, auth_client

router = APIRouter(prefix="/conversations", tags=["conversations"])

# ── Вложения чата (фото/видео, правки 2026-06-11) ────────────────────────────
_ATTACH_MAX_BYTES = 25 * 1024 * 1024  # 25 МБ
_ATTACH_EXT_MIME = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
}
_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
# Имя сохранённого файла: uuid4hex + разрешённое расширение
_ATTACH_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(jpg|jpeg|png|webp|gif|mp4|mov|webm)$")


class StartByPhoneRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32)


@router.post("/start-by-phone", response_model=ConversationListResponse)
async def start_by_phone(
    body: StartByPhoneRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Начать (или открыть существующий) прямой чат с пользователем по номеру телефона.

    Доступно всем ролям. Возвращает диалог; идемпотентно при повторном вызове.
    Блокировка мессенджера (правки 2026-06-11): заблокированный клиент не может
    начинать чаты; заблокированному клиенту могут писать только сотрудники.
    """
    if actor.role == "client" and await auth_client.is_messenger_blocked(redis, actor.id):
        raise HTTPException(status_code=403, detail="Доступ ограничен")

    target = await auth_client.lookup_by_phone(body.phone)
    if not target:
        raise HTTPException(status_code=404, detail="Пользователь с таким номером не найден")
    if (
        target.get("messenger_blocked")
        and target.get("role") == "client"
        and actor.role not in ("manager", "admin")
    ):
        # Заблокированного клиента «не находят» по номеру (кроме сотрудников)
        raise HTTPException(status_code=404, detail="Пользователь с таким номером не найден")
    target_id = uuid.UUID(target["id"])
    if target_id == actor.id:
        raise HTTPException(status_code=400, detail="Нельзя начать чат с самим собой")

    conv = await conversation_service.ensure_direct(db, actor.id, target_id)
    await db.commit()
    return ConversationListResponse(
        id=conv.id,
        kind=conv.kind,
        title=conv.title,
        client_id=conv.client_id,
        driver_id=conv.driver_id,
        order_id=conv.order_id,
        group_code=conv.group_code,
        created_by_id=conv.created_by_id,
        created_by_role=conv.created_by_role,
        unread_count=0,
        last_message=None,
        updated_at=conv.updated_at,
        peer_name=target.get("full_name"),
        peer_phone=target.get("phone"),
    )


@router.get("", response_model=list[ConversationListResponse])
async def list_conversations(
    order_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    rows = await conversation_service.list_conversations(db, actor, order_id)
    return [ConversationListResponse(**r) for r in rows]


@router.post("/ensure-client-manager", response_model=ConversationListResponse)
async def ensure_client_manager(
    body: EnsureClientManagerRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Ensure a client_manager conversation exists for the given client.

    Returns existing or newly created conversation. Staff-only endpoint used when
    a manager clicks the "Чат" button on a client card.
    """
    if actor.role not in ("manager", "admin"):
        raise ForbiddenError("Только менеджер или администратор")
    conv = await conversation_service.ensure_client_manager(db, body.client_id)
    await db.commit()
    return ConversationListResponse(
        id=conv.id,
        kind=conv.kind,
        title=conv.title,
        client_id=conv.client_id,
        driver_id=conv.driver_id,
        order_id=conv.order_id,
        group_code=conv.group_code,
        created_by_id=conv.created_by_id,
        created_by_role=conv.created_by_role,
        unread_count=0,
        last_message=None,
        updated_at=conv.updated_at,
    )


class EnsureClientAccountantRequest(BaseModel):
    # staff указывает клиента; клиент-юрлицо вызывает без тела (свой id)
    client_id: uuid.UUID | None = None


@router.post("/ensure-client-accountant", response_model=ConversationListResponse)
async def ensure_client_accountant(
    body: EnsureClientAccountantRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Чат клиента с бухгалтерией.

    Доступен клиенту, у которого есть хотя бы одна организация (единая модель).
    Клиент открывает свой; менеджер/админ — для любого клиента.
    Клиенту без организаций — 400.
    """
    if actor.role in ("manager", "admin"):
        if not body.client_id:
            raise HTTPException(status_code=422, detail="Укажите client_id")
        client_id = body.client_id
    elif actor.role == "client":
        client_id = actor.id
    else:
        raise ForbiddenError("Недоступно для этой роли")

    # Чат с бухгалтерией доступен клиенту, у которого есть хотя бы одна
    # организация (единая модель: «юрлицо» = наличие организаций, а не client_type).
    org_ids = await auth_client.get_organization_ids(client_id)
    if not org_ids:
        raise HTTPException(
            status_code=400,
            detail="Чат с бухгалтером доступен клиентам, у которых есть организация",
        )

    conv = await conversation_service.ensure_client_accountant(db, client_id)
    await db.commit()
    return ConversationListResponse(
        id=conv.id,
        kind=conv.kind,
        title=conv.title,
        client_id=conv.client_id,
        driver_id=conv.driver_id,
        order_id=conv.order_id,
        group_code=conv.group_code,
        created_by_id=conv.created_by_id,
        created_by_role=conv.created_by_role,
        unread_count=0,
        last_message=None,
        updated_at=conv.updated_at,
    )


class StaffGroupRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=80)
    member_ids: list[uuid.UUID] = Field(default_factory=list)


class StaffGroupMembersRequest(BaseModel):
    member_ids: list[uuid.UUID] = Field(default_factory=list)


def _conv_list_response(conv) -> ConversationListResponse:
    return ConversationListResponse(
        id=conv.id,
        kind=conv.kind,
        title=conv.title,
        client_id=conv.client_id,
        driver_id=conv.driver_id,
        order_id=conv.order_id,
        group_code=conv.group_code,
        created_by_id=conv.created_by_id,
        created_by_role=conv.created_by_role,
        unread_count=0,
        last_message=None,
        updated_at=conv.updated_at,
    )


@router.post("/staff-group", response_model=ConversationListResponse, status_code=201)
async def create_staff_group(
    body: StaffGroupRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Создать приватный групповой чат сотрудников (например «СЗТК»).

    Доступ к чату — только у явно добавленных участников (создатель + выбранные).
    Прочие менеджеры/админы чат НЕ видят. Только staff (admin/manager).
    """
    if actor.role not in ("manager", "admin"):
        raise ForbiddenError("Создавать групповые чаты может менеджер или администратор")
    conv = await conversation_service.create_private_group(
        db, actor, body.title, body.member_ids
    )
    await db.commit()
    return _conv_list_response(conv)


@router.put("/staff-group/{conv_id}/members", response_model=ConversationListResponse)
async def update_staff_group_members(
    conv_id: uuid.UUID,
    body: StaffGroupMembersRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Заменить состав участников приватной группы (доступно участникам-staff)."""
    conv = await conversation_service.set_private_group_members(
        db, actor, conv_id, body.member_ids
    )
    await db.commit()
    return _conv_list_response(conv)


class PinRequest(BaseModel):
    is_pinned: bool


@router.post("/{conv_id}/pin", status_code=204)
async def pin_conversation(
    conv_id: uuid.UUID,
    body: PinRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Закрепить/открепить чат для текущего пользователя (правки 2026-06-11)."""
    await conversation_service.set_pinned(db, conv_id, actor, body.is_pinned)


@router.get("/{conv_id}", response_model=ConversationResponse)
async def get_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    # Заблокированный клиент не может открыть переписку — «доступ ограничен»
    if actor.role == "client" and await auth_client.is_messenger_blocked(redis, actor.id):
        raise HTTPException(status_code=403, detail="Доступ ограничен")
    return await conversation_service.get_conversation(db, conv_id, actor)


@router.post("/{conv_id}/read", status_code=204)
async def mark_read(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    await conversation_service.mark_read(db, conv_id, actor)


@router.delete("/{conv_id}", status_code=204)
async def delete_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Hard-delete conversation and all messages — admin only."""
    await conversation_service.delete_conversation(db, conv_id, actor, redis=redis)


@router.post("/{conv_id}/clear", status_code=204)
async def clear_conversation(
    conv_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Clear message history — admin only."""
    await conversation_service.clear_conversation(db, conv_id, actor, redis=redis)


# --- Messages within a conversation ---

@router.get("/{conv_id}/messages", response_model=list[MessageResponse])
async def get_messages(
    conv_id: uuid.UUID,
    limit: int = 50,
    before_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    return await message_service.get_messages(db, conv_id, actor, limit, before_id)


@router.post("/{conv_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    conv_id: uuid.UUID,
    data: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    msg = await message_service.send_message(
        db, conv_id, data.text, actor, redis,
        msg_type=data.msg_type,
        metadata=data.metadata,
    )
    # Realtime-доставка REST-сообщений в открытые WS других участников
    # (раньше публиковал только WS-путь; вложения идут только через REST).
    try:
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "id": str(msg.id),
            "conversation_id": str(msg.conversation_id),
            "sender_id": str(msg.sender_id),
            "sender_role": msg.sender_role,
            "sender_name": msg.sender_name,
            "msg_type": msg.msg_type,
            "text": msg.text,
            "metadata": msg.msg_metadata,
            "created_at": msg.created_at.isoformat(),
        }))
    except Exception:
        pass
    return msg


# ── Вложения: фото/видео в чате (правки 2026-06-11) ──────────────────────────

@router.post("/{conv_id}/attachments")
async def upload_attachment(
    conv_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
    redis: aioredis.Redis = Depends(get_redis),
):
    """Загрузить фото/видео. Возвращает {path, mime, size, original_name, msg_type} —
    клиент затем отправляет сообщение msg_type=photo|video с этими metadata."""
    if actor.role == "client" and await auth_client.is_messenger_blocked(redis, actor.id):
        raise HTTPException(status_code=403, detail="Доступ ограничен")

    # Доступ к диалогу — та же проверка, что и при отправке сообщения
    from sqlalchemy import select as _select
    from app.models.conversation import Conversation as _Conv
    res = await db.execute(
        _select(_Conv).where(_Conv.id == conv_id, _Conv.is_archived == False)  # noqa: E712
    )
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    from app.services.conversation_service import _check_access
    _check_access(conv, actor)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ATTACH_EXT_MIME:
        raise HTTPException(
            status_code=415,
            detail="Допустимы фото (jpg/png/webp/gif) и видео (mp4/mov/webm)",
        )

    content = await file.read()
    if len(content) > _ATTACH_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 25 МБ")
    if not content:
        raise HTTPException(status_code=422, detail="Пустой файл")

    fname = f"{uuid.uuid4().hex}{ext}"
    dir_path = os.path.join(settings.media_root, "chat", str(conv_id))
    os.makedirs(dir_path, exist_ok=True)
    with open(os.path.join(dir_path, fname), "wb") as fh:
        fh.write(content)

    return {
        "path": fname,
        "mime": _ATTACH_EXT_MIME[ext],
        "size": len(content),
        "original_name": file.filename,
        "msg_type": "photo" if ext in _PHOTO_EXTS else "video",
    }


@router.get("/{conv_id}/attachments/{file_name}")
async def download_attachment(
    conv_id: uuid.UUID,
    file_name: str,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    """Отдать вложение участнику диалога. Имя файла строго uuid.ext — без traversal."""
    if not _ATTACH_NAME_RE.match(file_name):
        raise HTTPException(status_code=404, detail="Файл не найден")

    from sqlalchemy import select as _select
    from app.models.conversation import Conversation as _Conv
    res = await db.execute(_select(_Conv).where(_Conv.id == conv_id))
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Диалог не найден")
    from app.services.conversation_service import _check_access
    _check_access(conv, actor)

    fpath = os.path.join(settings.media_root, "chat", str(conv_id), file_name)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Файл не найден")
    ext = os.path.splitext(file_name)[1].lower()
    return FileResponse(fpath, media_type=_ATTACH_EXT_MIME.get(ext, "application/octet-stream"))


@router.delete("/{conv_id}/messages/{msg_id}", status_code=204)
async def delete_message(
    conv_id: uuid.UUID,
    msg_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: TokenUser = Depends(get_current_user),
):
    await message_service.delete_message(db, msg_id, actor)
