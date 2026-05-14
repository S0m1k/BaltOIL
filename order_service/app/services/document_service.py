"""
Генерация документов (счёт, ТТН, УПД) в PDF через WeasyPrint + Jinja2.

Файлы сохраняются в /app/media/documents/{order_id}/{doc_number}.pdf.
Путь записывается в Document.file_path для последующей отдачи клиенту.
"""
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentType, DocumentStatus
from app.models.order import Order
from app.core.dependencies import TokenUser
from app.core.exceptions import ValidationError, NotFoundError
from app.services.payment_service import get_seller_snapshot

log = logging.getLogger(__name__)

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", "/app/media"))
TEMPLATES_DIR = Path(__file__).parent.parent / "templates"

FUEL_LABELS = {
    "diesel_summer": "Дизельное топливо летнее (ДТ-Л)",
    "diesel_winter": "Дизельное топливо зимнее (ДТ-З)",
    "petrol_92":     "Бензин АИ-92",
    "petrol_95":     "Бензин АИ-95",
    "fuel_oil":      "Топочный мазут М-100",
}

# Базовые цены (₽/л) — берутся из payment_service; дублируем для документов
from app.services.payment_service import BASE_FUEL_PRICES, BASE_DELIVERY_PRICE_PER_LITER


# ── Jinja2 env ────────────────────────────────────────────────────────────────

def _make_jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["format_number"] = lambda v: f"{float(v):,.0f}".replace(",", " ")
    env.filters["format_money"]  = lambda v: f"{float(v):,.2f}".replace(",", " ")
    return env


_jinja_env: Environment | None = None


def _get_jinja_env() -> Environment:
    global _jinja_env
    if _jinja_env is None:
        _jinja_env = _make_jinja_env()
    return _jinja_env


# ── Document numbering ────────────────────────────────────────────────────────

async def _next_doc_number(db: AsyncSession, doc_type: DocumentType) -> str:
    """Генерировать номер документа: TTN-2026-000001 / UPD-2026-000001 / INV-2026-000001."""
    prefix = {"ttn": "TTN", "upd": "UPD", "invoice": "INV"}[doc_type.value]
    year = datetime.now(timezone.utc).year
    pattern = f"{prefix}-{year}-%"
    result = await db.execute(
        select(func.count()).select_from(Document)
        .where(Document.doc_number.like(pattern))
    )
    seq = (result.scalar() or 0) + 1
    return f"{prefix}-{year}-{seq:06d}"


# ── PDF rendering ─────────────────────────────────────────────────────────────

def _render_pdf(template_name: str, context: dict) -> bytes:
    """Рендерить HTML-шаблон → PDF через WeasyPrint."""
    from weasyprint import HTML as WP_HTML  # импорт здесь — тяжёлая библиотека
    env = _get_jinja_env()
    tmpl = env.get_template(template_name)
    html_str = tmpl.render(**context)
    return WP_HTML(string=html_str, base_url=str(TEMPLATES_DIR)).write_pdf()


def _save_pdf(order_id: uuid.UUID, doc_number: str, pdf_bytes: bytes) -> str:
    """Сохранить байты PDF на диск, вернуть относительный путь."""
    # Безопасное имя файла
    safe_name = re.sub(r"[^\w\-]", "_", doc_number) + ".pdf"
    doc_dir = MEDIA_ROOT / "documents" / str(order_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    file_path = doc_dir / safe_name
    file_path.write_bytes(pdf_bytes)
    # Возвращаем путь относительно MEDIA_ROOT для хранения в БД
    return str(file_path.relative_to(MEDIA_ROOT))


# ── Context builders ──────────────────────────────────────────────────────────

def _fuel_name(order: Order) -> str:
    fuel_val = order.fuel_type.value if hasattr(order.fuel_type, "value") else str(order.fuel_type)
    return FUEL_LABELS.get(fuel_val, fuel_val)


def _calc_unit_price(order: Order, volume: float) -> float:
    fuel_val = order.fuel_type.value if hasattr(order.fuel_type, "value") else str(order.fuel_type)
    fuel_price = BASE_FUEL_PRICES.get(fuel_val, 50.0)
    return round(fuel_price + BASE_DELIVERY_PRICE_PER_LITER, 2)


def _order_amount(order: Order, volume: float) -> float:
    if order.final_amount is not None:
        return float(order.final_amount)
    if order.expected_amount is not None:
        return float(order.expected_amount)
    return round(volume * _calc_unit_price(order, volume), 2)


def _buyer_snapshot_from_order(order: Order) -> dict:
    """Заглушка покупателя из заявки до интеграции с auth_service."""
    return {
        "name": str(order.client_id),
        "inn": "—",
        "kpp": None,
        "address": order.delivery_address,
    }


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_ttn(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
    driver_name: str = "—",
) -> Document:
    """Сформировать ТТН по факту доставки (DELIVERED / PARTIALLY_DELIVERED)."""
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order, volume)
    seller = await get_seller_snapshot(db)
    buyer  = _buyer_snapshot_from_order(order)
    doc_number = await _next_doc_number(db, DocumentType.TTN)

    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = {
        "doc_number":        doc_number,
        "issued_at":         now_str,
        "seller":            seller,
        "buyer":             buyer,
        "fuel_name":         _fuel_name(order),
        "order_number":      order.order_number,
        "delivery_address":  order.delivery_address,
        "volume_delivered":  volume,
        "amount":            amount,
        "driver_name":       driver_name,
        "order_status":      order.status.value,
    }

    try:
        pdf_bytes = _render_pdf("ttn.html", ctx)
        file_path = _save_pdf(order.id, doc_number, pdf_bytes)
        status = DocumentStatus.READY
    except Exception as exc:
        log.error("TTN PDF render failed for order %s: %s", order.id, exc)
        file_path = None
        status = DocumentStatus.DRAFT

    doc = Document(
        order_id=order.id,
        doc_type=DocumentType.TTN,
        doc_number=doc_number,
        status=status,
        seller_snapshot=seller,
        buyer_snapshot=buyer,
        issued_at=datetime.now(timezone.utc),
        total_amount=amount,
        volume=volume,
        file_path=file_path,
        created_by_id=actor.id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def generate_upd(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
) -> Document:
    """Сформировать УПД при закрытии заявки."""
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order, volume)
    unit_price = round(amount / volume, 2) if volume else 0
    seller = await get_seller_snapshot(db)
    buyer  = _buyer_snapshot_from_order(order)
    doc_number = await _next_doc_number(db, DocumentType.UPD)

    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = {
        "doc_number":        doc_number,
        "issued_at":         now_str,
        "seller":            seller,
        "buyer":             buyer,
        "fuel_name":         _fuel_name(order),
        "order_number":      order.order_number,
        "delivery_address":  order.delivery_address,
        "volume_delivered":  volume,
        "unit_price":        unit_price,
        "amount":            amount,
    }

    try:
        pdf_bytes = _render_pdf("upd.html", ctx)
        file_path = _save_pdf(order.id, doc_number, pdf_bytes)
        status = DocumentStatus.READY
    except Exception as exc:
        log.error("UPD PDF render failed for order %s: %s", order.id, exc)
        file_path = None
        status = DocumentStatus.DRAFT

    doc = Document(
        order_id=order.id,
        doc_type=DocumentType.UPD,
        doc_number=doc_number,
        status=status,
        seller_snapshot=seller,
        buyer_snapshot=buyer,
        issued_at=datetime.now(timezone.utc),
        total_amount=amount,
        volume=volume,
        file_path=file_path,
        created_by_id=actor.id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def generate_invoice_preliminary(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
) -> Document:
    """Предварительный счёт — выпускается при создании prepaid-заявки."""
    volume = float(order.volume_requested)
    amount = _order_amount(order, volume)
    seller = await get_seller_snapshot(db)
    buyer  = _buyer_snapshot_from_order(order)
    doc_number = await _next_doc_number(db, DocumentType.INVOICE_PRELIMINARY)

    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = {
        "doc_number":       doc_number,
        "issued_at":        now_str,
        "seller":           seller,
        "buyer":            buyer,
        "fuel_name":        _fuel_name(order),
        "order_number":     order.order_number,
        "delivery_address": order.delivery_address,
        "volume":           volume,
        "amount":           amount,
        "doc_title":        "Счёт на оплату (предварительный)",
    }

    try:
        pdf_bytes = _render_pdf("invoice.html", ctx)
        file_path = _save_pdf(order.id, doc_number, pdf_bytes)
        status = DocumentStatus.READY
    except Exception as exc:
        log.error("Invoice preliminary PDF render failed for order %s: %s", order.id, exc)
        file_path = None
        status = DocumentStatus.DRAFT

    doc = Document(
        order_id=order.id,
        doc_type=DocumentType.INVOICE_PRELIMINARY,
        doc_number=doc_number,
        status=status,
        seller_snapshot=seller,
        buyer_snapshot=buyer,
        issued_at=datetime.now(timezone.utc),
        total_amount=amount,
        volume=volume,
        file_path=file_path,
        created_by_id=actor.id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def generate_invoice_final(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
) -> Document:
    """Финальный счёт — выпускается при переходе в DELIVERED/PARTIALLY_DELIVERED."""
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order, volume)
    seller = await get_seller_snapshot(db)
    buyer  = _buyer_snapshot_from_order(order)
    doc_number = await _next_doc_number(db, DocumentType.INVOICE_FINAL)

    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = {
        "doc_number":       doc_number,
        "issued_at":        now_str,
        "seller":           seller,
        "buyer":            buyer,
        "fuel_name":        _fuel_name(order),
        "order_number":     order.order_number,
        "delivery_address": order.delivery_address,
        "volume":           volume,
        "amount":           amount,
        "doc_title":        "Счёт на оплату (финальный)",
    }

    try:
        pdf_bytes = _render_pdf("invoice.html", ctx)
        file_path = _save_pdf(order.id, doc_number, pdf_bytes)
        status = DocumentStatus.READY
    except Exception as exc:
        log.error("Invoice final PDF render failed for order %s: %s", order.id, exc)
        file_path = None
        status = DocumentStatus.DRAFT

    doc = Document(
        order_id=order.id,
        doc_type=DocumentType.INVOICE_FINAL,
        doc_number=doc_number,
        status=status,
        seller_snapshot=seller,
        buyer_snapshot=buyer,
        issued_at=datetime.now(timezone.utc),
        total_amount=amount,
        volume=volume,
        file_path=file_path,
        created_by_id=actor.id,
    )
    db.add(doc)
    await db.flush()
    return doc


async def get_document(db: AsyncSession, document_id: uuid.UUID) -> Document:
    result = await db.execute(select(Document).where(Document.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Документ не найден")
    return doc


async def list_for_order(db: AsyncSession, order_id: uuid.UUID) -> list[Document]:
    result = await db.execute(
        select(Document)
        .where(Document.order_id == order_id)
        .order_by(Document.created_at.desc())
    )
    return list(result.scalars().all())
