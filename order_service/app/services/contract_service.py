"""
Генерация договора поставки нефтепродуктов (PDF) и его учёт.

Договор живёт на клиенте (не на заявке): один активный договор на пару
(продавец, клиент). Реквизиты обеих сторон снимаются в JSONB на момент
заключения — изменение реквизитов не ломает уже выпущенный договор.

PDF сохраняется в MEDIA_ROOT/contracts/{client_id}/{contract_number}.pdf.
"""
import asyncio
import logging
import os
import re
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ValidationError
from app.models.contract import Contract, ContractMonthCounter, ContractStatus
from app.services.document_service import _render_pdf  # переиспользуем Jinja+WeasyPrint
from app.services.legal_entity_service import get_seller_snapshot

log = logging.getLogger(__name__)

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))

_MONTHS_RU = (
    "", "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


# ── Нумерация NNN/MM ───────────────────────────────────────────────────────────

async def _next_contract_number(db: AsyncSession) -> str:
    """Атомарно выдать номер вида '034/02' (seq за месяц / номер месяца)."""
    now = datetime.now(timezone.utc)
    month_key = f"{now.year:04d}-{now.month:02d}"
    stmt = (
        pg_insert(ContractMonthCounter)
        .values(month_key=month_key, last_seq=1)
        .on_conflict_do_update(
            index_elements=["month_key"],
            set_={"last_seq": ContractMonthCounter.last_seq + 1},
        )
        .returning(ContractMonthCounter.last_seq)
    )
    result = await db.execute(stmt)
    seq: int = result.scalar_one()
    return f"{seq:03d}/{now.month:02d}"


# ── Реквизиты покупателя из auth_service ───────────────────────────────────────

async def _fetch_buyer_legal_profile(client_id: uuid.UUID) -> dict:
    """Полные юр-реквизиты клиента для договора.

    404 от auth_service (физлицо / нет ИНН) → ValidationError: договор нельзя
    сформировать без реквизитов покупателя. Недоступность сервиса → 503.
    """
    base = settings.auth_service_url.rstrip("/")
    url = f"{base}/api/v1/internal/users/{client_id}/legal-profile"
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(url, headers=headers)
        if r.status_code == 404:
            raise ValidationError(
                "У клиента не заполнены юридические реквизиты — договор сформировать нельзя"
            )
        r.raise_for_status()
        return r.json()
    except ValidationError:
        raise
    except Exception as exc:
        log.error("auth_service legal-profile failed for %s: %s", client_id, exc)
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Сервис авторизации недоступен")


# ── Хелперы ────────────────────────────────────────────────────────────────────

def _short_sign_name(full_name: str | None) -> str:
    """'Борзяев Дмитрий Геннадьевич' → 'Борзяев Д.Г.' (для подписи)."""
    if not full_name:
        return "________________"
    parts = full_name.split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
    if len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return full_name


def _plus_five_years(d: date) -> date:
    try:
        return d.replace(year=d.year + 5)
    except ValueError:  # 29 февраля → 28-е
        return d.replace(year=d.year + 5, day=28)


def _save_contract_pdf(client_id: uuid.UUID, contract_number: str, pdf_bytes: bytes) -> str:
    safe_name = re.sub(r"[^\w\-]", "_", contract_number) + ".pdf"
    doc_dir = MEDIA_ROOT / "contracts" / str(client_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    file_path = doc_dir / safe_name
    file_path.write_bytes(pdf_bytes)
    return str(file_path.relative_to(MEDIA_ROOT))


async def get_active_contract(db: AsyncSession, client_id: uuid.UUID) -> Contract | None:
    result = await db.execute(
        select(Contract)
        .where(Contract.client_id == client_id, Contract.status == ContractStatus.ACTIVE)
        .order_by(Contract.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


# ── Уведомление admin+manager ──────────────────────────────────────────────────

async def _notify_contract_created(contract: Contract, pdf_bytes: bytes) -> None:
    """Письмо с PDF договора всем активным admin+manager. Best-effort — не падаем."""
    import base64

    auth_base = settings.auth_service_url.rstrip("/")
    notif_base = settings.notification_service_url.rstrip("/")
    headers = {"X-Internal-Secret": settings.internal_api_secret}
    client_name = (contract.buyer_snapshot or {}).get("name", "—")
    signed = contract.signed_at.strftime("%d.%m.%Y") if contract.signed_at else "—"
    until = contract.effective_until.strftime("%d.%m.%Y") if contract.effective_until else "—"

    subject = f"Договор № {contract.contract_number} с клиентом {client_name}"
    body = (
        f"Договор № {contract.contract_number} с клиентом {client_name} создан.\n\n"
        f"Дата заключения: {signed}\n"
        f"Действителен до: {until}\n\n"
        "Файл договора во вложении.\n\n"
        "—\nBaltOIL"
    )
    content_b64 = base64.b64encode(pdf_bytes).decode()
    safe_num = re.sub(r"[^\w\-]", "_", contract.contract_number)
    filename = f"contract_{safe_num}.pdf"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{auth_base}/api/v1/internal/users/admin-recipients", headers=headers)
            r.raise_for_status()
            recipients = r.json()
            for email in recipients:
                try:
                    await client.post(
                        f"{notif_base}/internal/email/send-with-attachment",
                        json={
                            "to": email,
                            "subject": subject,
                            "body": body,
                            "attachment": {
                                "filename": filename,
                                "content_base64": content_b64,
                                "mime_type": "application/pdf",
                            },
                        },
                        headers=headers,
                    )
                except Exception as exc:
                    log.warning("contract email to %s failed: %s", email, exc)
    except Exception as exc:
        log.warning("contract.notify failed for %s: %s", contract.contract_number, exc)


# ── Публичное API ───────────────────────────────────────────────────────────────

async def create_contract(
    db: AsyncSession,
    client_id: uuid.UUID,
    actor: TokenUser,
) -> Contract:
    """Сформировать договор поставки для клиента-юрлица.

    Идемпотентно: если активный договор уже есть — возвращаем его без повторной
    генерации и без письма.
    """
    # Транзакционный advisory-lock по клиенту сериализует параллельные создания
    # договора для одного клиента (защита от гонки «два активных договора»),
    # не требуя схемных изменений. Снимается автоматически на commit/rollback.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"contract:{client_id}"},
    )

    existing = await get_active_contract(db, client_id)
    if existing is not None:
        log.info("audit action=contract.skip_existing client_id=%s number=%s",
                 client_id, existing.contract_number)
        return existing

    seller = await get_seller_snapshot(db)
    if not seller:
        raise ValidationError("Реквизиты продавца не заданы — договор сформировать нельзя")
    buyer = await _fetch_buyer_legal_profile(client_id)

    contract_number = await _next_contract_number(db)
    signed_at = datetime.now(timezone.utc).date()
    effective_until = _plus_five_years(signed_at)

    ctx = {
        "contract_number":  contract_number,
        "city":             "Санкт-Петербург",
        "signed_day":       f"{signed_at.day:02d}",
        "signed_month_ru":  _MONTHS_RU[signed_at.month],
        "signed_year":      signed_at.year,
        "effective_until":  effective_until.strftime("%d.%m.%Y"),
        "seller":           seller,
        "buyer":            buyer,
        "seller_sign_name": _short_sign_name(seller.get("director_name")),
        "buyer_sign_name":  _short_sign_name(buyer.get("director_name")),
    }

    # WeasyPrint — CPU-bound; в отдельный поток, чтобы не блокировать event loop.
    pdf_bytes = await asyncio.to_thread(_render_pdf, "contract.html", ctx)
    file_path = _save_contract_pdf(client_id, contract_number, pdf_bytes)

    contract = Contract(
        client_id=client_id,
        contract_number=contract_number,
        seller_snapshot=seller,
        buyer_snapshot=buyer,
        signed_at=signed_at,
        effective_until=effective_until,
        status=ContractStatus.ACTIVE,
        file_path=file_path,
        created_by_id=actor.id,
    )
    db.add(contract)
    await db.flush()

    log.info("audit action=contract.created client_id=%s number=%s actor_id=%s",
             client_id, contract_number, actor.id)

    await _notify_contract_created(contract, pdf_bytes)
    return contract


def build_contract_export_ctx(contract: Contract) -> dict:
    """Контекст договора для выгрузки в docx (из сохранённого снимка)."""
    seller = contract.seller_snapshot or {}
    buyer = contract.buyer_snapshot or {}
    signed = contract.signed_at
    return {
        "contract_number":  contract.contract_number,
        "city":             "Санкт-Петербург",
        "signed_day":       f"{signed.day:02d}" if signed else "",
        "signed_month_ru":  _MONTHS_RU[signed.month] if signed else "",
        "signed_year":      signed.year if signed else "",
        "effective_until":  contract.effective_until.strftime("%d.%m.%Y") if contract.effective_until else "",
        "seller":           seller,
        "buyer":            buyer,
        "seller_sign_name": _short_sign_name(seller.get("director_name")),
        "buyer_sign_name":  _short_sign_name(buyer.get("director_name")),
    }


async def list_contracts(db: AsyncSession, client_id: uuid.UUID) -> list[Contract]:
    result = await db.execute(
        select(Contract)
        .where(Contract.client_id == client_id)
        .order_by(Contract.created_at.desc())
    )
    return list(result.scalars().all())


async def get_contract(db: AsyncSession, contract_id: uuid.UUID) -> Contract:
    result = await db.execute(select(Contract).where(Contract.id == contract_id))
    contract = result.scalar_one_or_none()
    if not contract:
        raise NotFoundError("Договор не найден")
    return contract
