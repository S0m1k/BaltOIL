import base64
import uuid
import logging
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime
import httpx
import redis.asyncio as aioredis

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.media import resolve_media_path
from app.core.exceptions import NotFoundError, ForbiddenError, ValidationError
from app.models.document import DocumentType, DocumentStatus
from app.models.order import OrderKind
from app.services import document_service
from app.services import document_export
from app.services.order_service import get_order
from app.config import settings
from pathlib import Path
import os

log = logging.getLogger(__name__)

router = APIRouter(prefix="/orders/{order_id}/documents", tags=["documents"])

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))

# Активные типы документов (Д4 2026-06-23: единый счёт). Новый INVOICE — основной;
# legacy preliminary/final оставлены в списке, чтобы старые заявки сохранили доступ
# к уже выпущенным счетам. Прочие типы (УПД/ТТН/договор/доверенность) — спящие.
ACTIVE_DOC_TYPES = (
    DocumentType.INVOICE,
    DocumentType.INVOICE_PRELIMINARY,
    DocumentType.INVOICE_FINAL,
)

# Ручное выставление счёта всегда работает с единым счётом (тот же номер при
# повторном вызове). Любой invoice-подобный doc_type маппится на единый генератор.
_INVOICE_DOC_TYPES = {"invoice", "invoice_preliminary", "invoice_final"}


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


class GenerateDocumentRequest(BaseModel):
    doc_type: str = "invoice"  # единый счёт; legacy-значения принимаются как алиасы


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    order_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Список документов по заявке (клиент видит только свои заявки).

    Д4: выдаются только активные типы (предв./финальный счёт), оба видны клиенту.
    Спящие типы (УПД/ТТН/договор/доверенность/legacy) скрыты для всех ролей.
    """
    await get_order(db, order_id, actor)  # проверка доступа
    docs = await document_service.list_for_order(db, order_id)
    active = [d for d in docs if d.doc_type in ACTIVE_DOC_TYPES]
    # Единый счёт: если по заявке есть новый INVOICE — показываем только его,
    # legacy предв./финальный скрываем (иначе у старых заявок было бы 2-3 счёта).
    has_unified = any(d.doc_type == DocumentType.INVOICE for d in active)
    if has_unified:
        active = [d for d in active if d.doc_type == DocumentType.INVOICE]
    return active


@router.post("/generate", response_model=DocumentResponse, status_code=201)
async def generate_document(
    order_id: uuid.UUID,
    body: GenerateDocumentRequest,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Выставить счёт вручную (менеджер/админ).

    Нужно прежде всего для заявок >= 3000 л, где автогенерация отключена, а также
    как общий механизм повторного выставления. Генераторы идемпотентны — повторный
    вызов вернёт уже выпущенный документ без создания дубля.
    """
    if actor.role not in ("manager", "admin"):
        raise ForbiddenError("Выставлять счета может менеджер или администратор")

    if body.doc_type not in _INVOICE_DOC_TYPES:
        raise ValidationError("doc_type должен быть invoice")

    order = await get_order(db, order_id, actor)  # проверка доступа
    if order.order_kind == OrderKind.TTN_L:
        raise ValidationError("Для ТТН-Л счета не выставляются")

    # Единый счёт: перевыпуск с теми же номером/датой и актуальными цифрами
    # (или создание, если счёта ещё нет).
    doc = await document_service.regenerate_invoice(db, order, actor)
    await db.commit()
    await db.refresh(doc)
    return doc


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

    full_path = resolve_media_path(MEDIA_ROOT, doc.file_path)
    if not full_path.exists():
        raise NotFoundError("Файл не найден на сервере")

    return FileResponse(
        path=str(full_path),
        media_type="application/pdf",
        filename=f"{doc.doc_number}.pdf",
    )


@router.get("/{document_id}/export")
async def export_document(
    order_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Выгрузить документ в редактируемом формате (xlsx — счёт/ТТН/УПД, docx — доверенность).

    Файл строится на лету из сохранённого снимка документа, поэтому совпадает
    с выпущенным PDF и доступен для уже существующих документов.
    """
    order = await get_order(db, order_id, actor)  # проверка доступа
    doc = await document_service.get_document(db, document_id)
    if doc.order_id != order_id:
        raise ForbiddenError("Документ не принадлежит этой заявке")
    if doc.status not in (DocumentStatus.READY, DocumentStatus.SENT):
        raise NotFoundError("Документ ещё не готов")

    dtype = doc.doc_type.value if hasattr(doc.doc_type, "value") else str(doc.doc_type)
    try:
        ctx = await document_service.build_export_ctx(db, doc, order)
        content, ext, mime = document_export.export_document(dtype, ctx)
    except ValueError as exc:
        raise ValidationError(str(exc))

    filename = f"{doc.doc_number}.{ext}"
    return Response(
        content=content,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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
                # Нет диалога по заявке — гарантируем диалог клиент ↔ менеджер.
                # Раньше тут был POST /conversations, которого в chat_service нет
                # (есть только ensure-*-эндпоинты) → отправка падала с 404.
                r2 = await client.post(
                    f"{base}/api/v1/conversations/ensure-client-manager",
                    json={"client_id": str(order.client_id)},
                    headers=headers,
                )
                r2.raise_for_status()
                conv_id = r2.json()["id"]

            # Отправляем document-сообщение
            doc_type_label = {
                "invoice": "Счёт",
                "invoice_preliminary": "Счёт",
                "invoice_final": "Счёт",
                "ttn": "ТТН",
                "upd": "УПД",
            }.get(
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


async def _check_send_email_rate(actor_id: uuid.UUID) -> None:
    """Лимит 5 отправок документов в минуту на пользователя. Защита от спама/DoS.

    Считаем общее количество отправок этого менеджера, а не per-document — иначе
    можно слать тот же документ в цикле меняя document_id (для разных заявок).
    """
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = f"send_email_rl:{actor_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 60)
        if n > 5:
            raise HTTPException(status_code=429, detail="too many email sends; wait 1 minute")
    finally:
        await r.aclose()


@router.post("/{document_id}/send-email", status_code=200)
async def send_document_by_email(
    order_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Отправить PDF документа клиенту на email.

    Адрес получателя берётся ТОЛЬКО из профиля клиента заявки (billing_email
    или user.email через auth_service). Произвольный адрес в теле запроса не
    принимаем — иначе менеджер может слать чужие документы куда угодно.

    Доступно менеджеру и администратору. Rate-limit: 5 отправок/мин на пользователя.
    При ошибке SMTP — 503, статус документа не меняется.
    """
    if actor.role not in ("manager", "admin"):
        raise ForbiddenError("Отправлять документы по email может менеджер или администратор")

    await _check_send_email_rate(actor.id)

    order = await get_order(db, order_id, actor)
    doc = await document_service.get_document(db, document_id)

    if doc.order_id != order_id:
        raise ForbiddenError("Документ не принадлежит этой заявке")

    # READY и SENT оба допустимы для повторной отправки
    if doc.status not in (DocumentStatus.READY, DocumentStatus.SENT):
        raise HTTPException(status_code=409, detail="document not ready")

    if not doc.file_path:
        raise NotFoundError("document file missing")

    full_path = resolve_media_path(MEDIA_ROOT, doc.file_path)
    if not full_path.exists():
        raise NotFoundError("document file missing")

    # Адрес получателя — только из профиля клиента, без override из тела
    auth_base = settings.auth_service_url.rstrip("/")
    internal_headers = {"X-Internal-Secret": settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{auth_base}/api/v1/internal/users/{order.client_id}/email-target",
                headers=internal_headers,
            )
            r.raise_for_status()
            recipient = r.json().get("email")
    except Exception as exc:
        log.error("auth_service email-target lookup failed: %s", exc)
        raise HTTPException(status_code=503, detail="email service unavailable")

    if not recipient:
        raise HTTPException(status_code=422, detail="recipient has no email")

    # Читаем PDF и кодируем
    pdf_bytes = full_path.read_bytes()
    content_b64 = base64.b64encode(pdf_bytes).decode()

    # Составляем тему письма: "Документ ИНВ-2026-000123 по заявке ORD-2026-000045"
    subject = f"Документ {doc.doc_number} по заявке {order.order_number}"
    body_text = (
        "Здравствуйте,\n\n"
        "Во вложении документ по вашей заявке.\n\n"
        "— BaltOIL"
    )
    filename = f"{doc.doc_number}.pdf"

    # Вызываем notification_service
    notif_base = settings.notification_service_url.rstrip("/")
    internal_headers = {"X-Internal-Secret": settings.internal_api_secret}
    sent = False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(
                f"{notif_base}/internal/email/send-with-attachment",
                json={
                    "to": recipient,
                    "subject": subject,
                    "body": body_text,
                    "attachment": {
                        "filename": filename,
                        "content_base64": content_b64,
                        "mime_type": "application/pdf",
                    },
                },
                headers=internal_headers,
            )
            r.raise_for_status()
            sent = r.json().get("sent", False)
    except Exception as exc:
        log.error("notification_service send-with-attachment failed: %s", exc)

    if not sent:
        raise HTTPException(status_code=503, detail="email service unavailable")

    # Только после подтверждения от notification_service обновляем статус
    doc.status = DocumentStatus.SENT
    await db.commit()

    log.info(
        "document.sent_email action document_id=%s order_id=%s to=%s filename=%s",
        document_id, order_id, recipient, filename,
    )

    return {"ok": True, "to": recipient}
