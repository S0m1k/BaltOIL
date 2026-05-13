import uuid
import logging
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime
import httpx

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.models.document import DocumentType, DocumentStatus
from app.services import document_service
from app.services.order_service import get_order
from app.config import settings
from pathlib import Path
import os

log = logging.getLogger(__name__)

router = APIRouter(prefix="/orders/{order_id}/documents", tags=["documents"])

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))


class DocumentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    doc_type: DocumentType
    doc_number: str
    status: DocumentStatus
    issued_at: datetime | None
    total_amount: float | None
    volume: float | None
    file_path: str | None
    created_by_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    order_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Список документов по заявке (клиент видит только свои заявки)."""
    await get_order(db, order_id, actor)  # проверка доступа
    return await document_service.list_for_order(db, order_id)


@router.get("/{document_id}/download")
async def download_document(
    order_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Скачать PDF документа."""
    await get_order(db, order_id, actor)  # проверка доступа к заявке
    doc = await document_service.get_document(db, document_id)

    if doc.order_id != order_id:
        raise ForbiddenError("Документ не принадлежит этой заявке")
    if doc.status != DocumentStatus.READY or not doc.file_path:
        raise NotFoundError("PDF ещё не готов")

    full_path = MEDIA_ROOT / doc.file_path
    if not full_path.exists():
        raise NotFoundError("Файл не найден на сервере")

    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        filename=f"{doc.doc_number}.pdf",
    )


@router.post("/{document_id}/send", status_code=200)
async def send_document_to_chat(
    order_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Отправить документ в чат по заявке.

    Находит или создаёт диалог заявки, отправляет сообщение типа 'document',
    обновляет статус документа на SENT.
    Доступно менеджеру и администратору.
    """
    if actor.role not in ("manager", "admin"):
        raise ForbiddenError("Отправлять документы в чат может менеджер или администратор")

    order = await get_order(db, order_id, actor)
    doc = await document_service.get_document(db, document_id)

    if doc.order_id != order_id:
        raise ForbiddenError("Документ не принадлежит этой заявке")
    if doc.status == DocumentStatus.DRAFT:
        raise ValidationError("PDF ещё не сгенерирован (статус DRAFT). Дождитесь генерации.")

    # Находим диалог по заявке через chat_service
    base = settings.chat_service_url.rstrip("/")
    headers = {"Authorization": f"Bearer {actor.token}"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Ищем существующий диалог по order_id
            r = await client.get(
                f"{base}/api/v1/conversations",
                params={"order_id": str(order_id)},
                headers=headers,
            )
            r.raise_for_status()
            convs = r.json()

            if convs:
                conv_id = convs[0]["id"]
            else:
                # Создаём диалог клиент ↔ менеджер по заявке
                r2 = await client.post(
                    f"{base}/api/v1/conversations",
                    json={
                        "type": "client_support",
                        "order_id": str(order_id),
                        "participant_ids": [str(order.client_id)],
                        "title": f"Заявка {order.order_number}",
                    },
                    headers=headers,
                )
                r2.raise_for_status()
                conv_id = r2.json()["id"]

            # Отправляем document-сообщение
            doc_type_label = {"invoice": "Счёт", "ttn": "ТТН", "upd": "УПД"}.get(
                doc.doc_type.value if hasattr(doc.doc_type, "value") else doc.doc_type, "Документ"
            )
            msg_text = f"📄 {doc_type_label} {doc.doc_number} по заявке {order.order_number}"

            r3 = await client.post(
                f"{base}/api/v1/conversations/{conv_id}/messages",
                json={
                    "text": msg_text,
                    "msg_type": "document",
                    "metadata": {
                        "document_id": str(doc.id),
                        "doc_number": doc.doc_number,
                        "doc_type": doc.doc_type.value if hasattr(doc.doc_type, "value") else doc.doc_type,
                        "order_id": str(order_id),
                        "order_number": order.order_number,
                        "download_path": f"/api/v1/orders/{order_id}/documents/{document_id}/download",
                    },
                },
                headers=headers,
            )
            r3.raise_for_status()

    except httpx.HTTPStatusError as exc:
        log.error("Chat service error sending doc %s: %s %s", document_id, exc.response.status_code, exc.response.text)
        raise ValidationError(f"Ошибка чат-сервиса: {exc.response.status_code}")
    except httpx.RequestError as exc:
        log.error("Chat service unreachable: %s", exc)
        raise ValidationError("Чат-сервис недоступен")

    # Отмечаем документ как отправленный
    doc.status = DocumentStatus.SENT
    await db.commit()

    return {"ok": True, "conv_id": conv_id}
