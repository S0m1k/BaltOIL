"""
Договоры поставки (Sprint 2026-07 Деплой 2).

Договор живёт на клиенте. Генерация и список — manager/admin. Скачивание —
manager/admin для любого договора, клиент — только своего.
"""
import base64
import logging
import os
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser, require_roles
from app.core.media import resolve_media_path
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.models.contract import ContractStatus
from app.services import contract_service
from app.services import document_export
from app.config import settings

log = logging.getLogger(__name__)

router = APIRouter(tags=["contracts"])


async def _fetch_contract_target(org_id: uuid.UUID) -> dict:
    """Цель договора организации (владелец, почта, участники) из auth_service."""
    base = settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    async with httpx.AsyncClient(timeout=5.0) as client:
        r = await client.get(
            f"{base}/api/v1/internal/organizations/{org_id}/contract-target",
            headers=headers,
        )
        r.raise_for_status()
        return r.json()

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


class RegenerateContractRequest(BaseModel):
    contract_number: str | None = None
    signed_at: date | None = None


class ContractRegistryRow(BaseModel):
    id: uuid.UUID
    contract_number: str
    organization_id: uuid.UUID | None
    organization_name: str | None
    signed_at: date | None
    created_at: datetime
    status: ContractStatus


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


async def _fetch_buyer_names(items: list[dict]) -> dict[str, str]:
    """Имена покупателей (клиент/организация) батчем из auth_service.

    Ключ карты: f"{client_id}|{organization_id or ''}". При недоступности
    auth_service возвращает пустую карту — не падаем (organization_name=None).
    """
    if not items:
        return {}
    base = settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{base}/api/v1/internal/orders/buyer-names",
                json={"items": items},
                headers=headers,
            )
            r.raise_for_status()
            rows = r.json()
    except Exception as exc:
        log.warning("buyer-names lookup failed: %s", exc)
        return {}
    names: dict[str, str] = {}
    for row in rows:
        key = f"{row.get('client_id')}|{row.get('organization_id') or ''}"
        names[key] = row.get("name")
    return names


@router.get("/contracts", response_model=list[ContractRegistryRow])
async def list_contracts_registry(
    actor: CurrentUser,
    _: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Реестр всех договоров (staff-only)."""
    contracts = await contract_service.list_all_contracts(db)
    items = [
        {
            "client_id": str(c.client_id),
            "organization_id": str(c.organization_id) if c.organization_id else None,
        }
        for c in contracts
    ]
    names = await _fetch_buyer_names(items)
    rows = []
    for c in contracts:
        key = f"{c.client_id}|{c.organization_id or ''}"
        rows.append(
            ContractRegistryRow(
                id=c.id,
                contract_number=c.contract_number,
                organization_id=c.organization_id,
                organization_name=names.get(key),
                signed_at=c.signed_at,
                created_at=c.created_at,
                status=c.status,
            )
        )
    return rows


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


@router.patch("/contracts/{contract_id}/regenerate", response_model=ContractResponse)
async def regenerate_contract(
    contract_id: uuid.UUID,
    payload: RegenerateContractRequest,
    actor: CurrentUser,
    _: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Перевыпустить договор с новым номером и/или датой подписания (staff-only)."""
    contract = await contract_service.get_contract(db, contract_id)
    contract = await contract_service.regenerate_contract(
        db,
        contract,
        actor,
        new_number=payload.contract_number,
        new_signed_at=payload.signed_at,
    )
    await db.commit()
    await db.refresh(contract)
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


# ── Договор по организации (кнопка «Договор» на карточке юрлица, правки 2026-06-23) ──

@router.get("/organizations/{org_id}/contract", response_model=ContractResponse)
async def get_org_contract(
    org_id: uuid.UUID,
    actor: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Договор организации (находит активный, иначе формирует). Доступ: staff —
    всегда; клиент — только участник организации."""
    try:
        target = await _fetch_contract_target(org_id)
    except Exception as exc:
        log.error("contract-target lookup failed for org %s: %s", org_id, exc)
        raise HTTPException(status_code=503, detail="Сервис организаций недоступен")

    member_ids = set(target.get("member_ids") or [])
    is_staff = actor.role in ("manager", "admin")
    if not is_staff and str(actor.id) not in member_ids:
        raise ForbiddenError("Договор доступен только сотрудникам организации")

    contract = await contract_service.get_active_contract_by_org(db, org_id)
    if contract is None:
        owner_id = target.get("owner_client_id")
        if not owner_id:
            raise HTTPException(status_code=422, detail="У организации нет активных участников")
        contract = await contract_service.create_contract(
            db, uuid.UUID(owner_id), actor, org_id
        )
        await db.commit()
        await db.refresh(contract)
    return contract


async def _resolve_contract_recipient(contract) -> str | None:
    """Email для отправки договора: billing_email организации, иначе email владельца."""
    if contract.organization_id:
        try:
            target = await _fetch_contract_target(contract.organization_id)
            if target.get("billing_email"):
                return target["billing_email"]
        except Exception as exc:
            log.warning("contract recipient org lookup failed: %s", exc)
    # Fallback — email клиента-владельца через auth_service
    base = settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/api/v1/internal/users/{contract.client_id}/email-target",
                headers=headers,
            )
            r.raise_for_status()
            return r.json().get("email")
    except Exception as exc:
        log.warning("contract recipient email-target lookup failed: %s", exc)
        return None


@router.post("/contracts/{contract_id}/send-email", status_code=200)
async def send_contract_by_email(
    contract_id: uuid.UUID,
    actor: CurrentUser,
    _: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Отправить PDF договора на почту организации (или владельца). Только staff."""
    contract = await contract_service.get_contract(db, contract_id)
    if not contract.file_path:
        raise NotFoundError("PDF договора не готов")
    full_path = resolve_media_path(MEDIA_ROOT, contract.file_path)
    if not full_path.exists():
        raise NotFoundError("Файл договора не найден")

    recipient = await _resolve_contract_recipient(contract)
    if not recipient:
        raise HTTPException(status_code=422, detail="Не задан email для отправки договора")

    content_b64 = base64.b64encode(full_path.read_bytes()).decode()
    subject = f"Договор № {contract.contract_number}"
    body_text = "Здравствуйте,\n\nВо вложении договор поставки нефтепродуктов.\n\n— СЗТК"
    filename = f"Договор_{contract.contract_number.replace('/', '-')}.pdf"

    notif_base = settings.notification_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
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
                headers=headers,
            )
            r.raise_for_status()
            sent = r.json().get("sent", False)
    except Exception as exc:
        log.error("contract send-email failed: %s", exc)

    if not sent:
        raise HTTPException(status_code=503, detail="Почтовый сервис недоступен")

    log.info("contract.sent_email contract_id=%s to=%s", contract_id, recipient)
    return {"ok": True, "to": recipient}


