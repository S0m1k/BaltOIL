"""
Генерация документов (счёт, ТТН, УПД) в PDF через WeasyPrint + Jinja2.

Файлы сохраняются в /app/media/documents/{order_id}/{doc_number}.pdf.
Путь записывается в Document.file_path для последующей отдачи клиенту.
"""
import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from num2words import num2words
from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document, DocumentType, DocumentStatus, DocNumberCounter
from app.models.order import Order
from app.core.dependencies import TokenUser
from app.core.exceptions import ValidationError, NotFoundError
from app.services.legal_entity_service import get_seller_snapshot


# ── Сумма прописью ────────────────────────────────────────────────────────────

_KOPECK_FORMS = ("копейка", "копейки", "копеек")
_RUBLE_FORMS  = ("рубль", "рубля", "рублей")


def _ru_plural(n: int, forms: tuple[str, str, str]) -> str:
    """forms = (1, 2-4, 5-20). Корректно склоняет существительное по числу."""
    n = abs(n) % 100
    if 10 < n < 20:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def amount_to_words_ru(amount: float | Decimal) -> str:
    """3168.50 → 'Три тысячи сто шестьдесят восемь рублей 50 копеек'."""
    total_kopecks = int(round(float(amount) * 100))
    rubles = total_kopecks // 100
    kopecks = total_kopecks % 100
    rub_words = num2words(rubles, lang="ru")
    rub_text = rub_words[0].upper() + rub_words[1:]
    return (
        f"{rub_text} {_ru_plural(rubles, _RUBLE_FORMS)} "
        f"{kopecks:02d} {_ru_plural(kopecks, _KOPECK_FORMS)}"
    )

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
    """Сгенерировать номер документа: TTN-2026-000001 / UPD-2026-000001 / INV-2026-000001.

    Атомарно через DocNumberCounter (INSERT ... ON CONFLICT DO UPDATE ... RETURNING) —
    как нумерация заказов/договоров. Прежний COUNT(*)+1 давал гонки: две одновременные
    доставки получали один номер → IntegrityError на flush внутри транзакции перехода.
    """
    prefix = {
        "ttn": "TTN",
        "upd": "UPD",
        "poa": "POA",
        "invoice": "INV",
        "invoice_preliminary": "INV",
        "invoice_final": "INV",
    }[doc_type.value]
    year = datetime.now(timezone.utc).year
    prefix_key = f"{prefix}-{year}"
    stmt = (
        pg_insert(DocNumberCounter)
        .values(prefix_key=prefix_key, last_seq=1)
        .on_conflict_do_update(
            index_elements=["prefix_key"],
            set_={"last_seq": DocNumberCounter.last_seq + 1},
        )
        .returning(DocNumberCounter.last_seq)
    )
    seq: int = (await db.execute(stmt)).scalar_one()
    return f"{prefix}-{year}-{seq:06d}"


async def _existing_document(
    db: AsyncSession, order_id: uuid.UUID, doc_type: DocumentType
) -> Document | None:
    """Уже выпущенный (не аннулированный) документ этого типа по заявке — для идемпотентности.

    Повторный рейс (PARTIALLY_DELIVERED → ACCEPTED → IN_TRANSIT → DELIVERED) иначе
    плодил бы дубли POA/ТТН/УПД/счёта с новыми номерами и собственными суммами.
    """
    result = await db.execute(
        select(Document).where(
            Document.order_id == order_id,
            Document.doc_type == doc_type,
            Document.status != DocumentStatus.CANCELLED,
        ).limit(1)
    )
    return result.scalar_one_or_none()


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


# ── Invoice context (по образцу заказчика) ────────────────────────────────────

# Дефолтная ставка НДС, если в seller-снимке не указано. Образец заказчика —
# 22%. Когда в LegalEntity появится поле vat_rate, использовать оттуда.
DEFAULT_VAT_RATE = 22


def _split_fuel_delivery(order: Order, volume: float, total_amount: float) -> tuple[float, float]:
    """Разделить total_amount на (стоимость топлива, стоимость доставки).

    Берёт долю топлива и доставки из BASE_* как соотношение, потом масштабирует
    под фактический total_amount (он может отличаться, если менеджер выставил
    final_amount/expected_amount вручную).
    """
    fuel_val = order.fuel_type.value if hasattr(order.fuel_type, "value") else str(order.fuel_type)
    fuel_price = BASE_FUEL_PRICES.get(fuel_val, 50.0)
    base_fuel = volume * fuel_price
    base_delivery = volume * BASE_DELIVERY_PRICE_PER_LITER
    base_total = base_fuel + base_delivery
    if base_total <= 0:
        return total_amount, 0.0
    fuel_share = base_fuel / base_total
    fuel_sum = round(total_amount * fuel_share, 2)
    delivery_sum = round(total_amount - fuel_sum, 2)
    return fuel_sum, delivery_sum


def _build_invoice_ctx(
    *,
    doc_number: str,
    issued_at: str,
    seller: dict | None,
    buyer: dict,
    order: Order,
    volume: float,
    total_amount: float,
    basis: str = "",
) -> dict:
    """Контекст для invoice.html — образец заказчика (Обр счета.xls)."""
    _seller_vat = (seller or {}).get("vat_rate")
    vat_rate = DEFAULT_VAT_RATE if _seller_vat is None else _seller_vat
    items, subtotal, vat_amount, total = _build_line_items(order, volume, total_amount, vat_rate)
    fuel_unit_price = items[0]["price"] if items else 0.0

    return {
        "doc_number":      doc_number,
        "issued_at":       issued_at,
        "seller":          seller or {},
        "buyer":           buyer,
        "basis":           basis,
        "items":           items,
        "subtotal":        subtotal,      # пред-НДС
        "vat_rate":        vat_rate,
        "vat_amount":      vat_amount,
        "total":           total,         # с НДС = total_amount (то, что платит клиент)
        "amount_in_words": amount_to_words_ru(total),
        # Legacy переменные на случай если шаблон откатится:
        "fuel_name":        _fuel_name(order),
        "order_number":     order.order_number,
        "delivery_address": order.delivery_address,
        "volume":           volume,
        "amount":           total,
        "unit_price":       fuel_unit_price,
    }


def _build_line_items(
    order: Order, volume: float, total_amount: float, vat_rate: int
) -> tuple[list[dict], float, float, float]:
    """Разбить заказ на позиции (топливо + доставка) с разбивкой НДС.

    total_amount — сумма С НДС (то, что клиент платит, как order.expected/final_amount,
    на этой сумме строится учёт долга). В образце счёта строки и «Итого» показаны
    БЕЗ НДС, НДС добавляется отдельной строкой, «Всего к оплате» = с НДС. Поэтому
    раскладываем total_amount обратно на пред-НДС базу и налог.

    Возвращает (items, subtotal_no_vat, vat_amount, total), где total == total_amount.
    """
    rate = vat_rate or 0
    pre_vat_total = round(total_amount / (1 + rate / 100), 2) if rate else total_amount
    fuel_pre, delivery_pre = _split_fuel_delivery(order, volume, pre_vat_total)

    def _line(name: str, qty: float, unit: str, unit_code: str | None, sum_no_vat: float) -> dict:
        vat = round(sum_no_vat * rate / 100, 2)
        return {
            "name":       name,
            "qty":        qty,
            "unit":       unit,
            "unit_code":  unit_code,
            "price":      round(sum_no_vat / qty, 2) if qty else 0.0,
            "sum_no_vat": sum_no_vat,
            "vat":        vat,
            "sum":        round(sum_no_vat + vat, 2),
        }

    items = [_line(_fuel_name(order), volume, "л", "112", fuel_pre)]
    if delivery_pre > 0:
        items.append(_line(f"Доставка по адресу: {order.delivery_address}", 1, "рейс", None, delivery_pre))

    subtotal_no_vat = round(sum(i["sum_no_vat"] for i in items), 2)
    # Налог считаем как разницу, чтобы «Всего» точно совпало с total_amount (учёт долга).
    vat_amount = round(total_amount - subtotal_no_vat, 2)
    return items, subtotal_no_vat, vat_amount, total_amount


def _build_upd_ctx(
    *,
    doc_number: str,
    issued_at: str,
    seller: dict | None,
    buyer: dict,
    order: Order,
    volume: float,
    total_amount: float,
) -> dict:
    """Контекст для upd.html — официальная форма (Постановление Правительства РФ N 1137)."""
    _seller_vat = (seller or {}).get("vat_rate")
    vat_rate = DEFAULT_VAT_RATE if _seller_vat is None else _seller_vat
    items, subtotal, vat_amount, total = _build_line_items(order, volume, total_amount, vat_rate)
    return {
        "doc_number":       doc_number,
        "issued_at":        issued_at,
        "seller":           seller or {},
        "buyer":            buyer,
        "status_code":      "1" if vat_rate else "2",  # 1 = СФ+передаточный, 2 = только передаточный
        "items":            items,
        "subtotal":         subtotal,
        "vat_rate":         vat_rate,
        "vat_amount":       vat_amount,
        "total":            total,
        "order_number":     order.order_number,
        "delivery_address": order.delivery_address,
        "basis":            f"Заявка №{order.order_number}",
        "transport_info":   "—",
    }


def _buyer_snapshot_from_order(order: Order) -> dict:
    """Fallback покупателя, если auth_service недоступен."""
    return {
        "name": str(order.client_id),
        "inn": "—",
        "kpp": None,
        "address": order.delivery_address,
    }


async def _fetch_buyer_snapshot(order: Order) -> dict:
    """Тянем реквизиты покупателя из auth_service.

    Не падаем при недоступности — клонируем fallback на UUID, чтобы документ
    хотя бы сгенерировался (документ — критичный артефакт, лучше с прочерком
    чем не сформировать вовсе).
    """
    import httpx
    from app.config import settings as _settings
    base = _settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": _settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/api/v1/internal/clients/{order.client_id}/buyer-snapshot",
                headers=headers,
            )
            r.raise_for_status()
            b = r.json()
            return {
                "name":    b.get("name") or str(order.client_id),
                "inn":     b.get("inn") or "—",
                "kpp":     b.get("kpp"),
                "ogrn":    b.get("ogrn"),
                "address": b.get("legal_address") or order.delivery_address,
                "director_name": b.get("director_name"),
            }
    except Exception as exc:
        log.warning("auth_service buyer-snapshot failed for %s: %s", order.client_id, exc)
        return _buyer_snapshot_from_order(order)


async def _fetch_driver_profile(driver_id: uuid.UUID | None) -> dict:
    """ФИО + паспорт водителя из auth_service для доверенности (POA).

    Любая ошибка/отсутствие водителя → пустой dict: доверенность всё равно
    формируется, в PDF на месте данных будет прочерк.
    """
    if driver_id is None:
        return {}
    import httpx
    from app.config import settings as _settings
    base = _settings.auth_service_url.rstrip("/")
    headers = {"X-Internal-Secret": _settings.internal_api_secret}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/api/v1/internal/users/{driver_id}/profile",
                headers=headers,
            )
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        log.warning("auth_service driver profile failed for %s: %s", driver_id, exc)
        return {}


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
    buyer  = await _fetch_buyer_snapshot(order)
    existing = await _existing_document(db, order.id, DocumentType.TTN)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.TTN)

    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    unit_price = round(amount / volume, 2) if volume else 0.0
    ctx = {
        "doc_number":        doc_number,
        "issued_at":         now_str,
        "seller":            seller,
        "buyer":             buyer,
        "fuel_name":         _fuel_name(order),
        "order_number":      order.order_number,
        "delivery_address":  order.delivery_address,
        "volume":            volume,
        "volume_delivered":  volume,
        "unit_price":        unit_price,
        "amount":            amount,
        "amount_in_words":   amount_to_words_ru(amount),
        "driver_name":       driver_name or "—",
        "order_status":      order.status.value,
    }

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf,"ttn.html", ctx)
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


async def generate_poa(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
) -> Document:
    """Сформировать доверенность (М-2) на получение ТМЦ водителем.

    Триггер — переход заявки в IN_TRANSIT. Паспорт водителя тянем из auth_service;
    если не заполнен/водитель не назначен — в PDF прочерк, в логе warning.
    """
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order, volume)
    seller = await get_seller_snapshot(db)
    buyer  = await _fetch_buyer_snapshot(order)
    driver = await _fetch_driver_profile(order.driver_id)
    existing = await _existing_document(db, order.id, DocumentType.POA)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.POA)
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%d.%m.%Y")
    valid_until = (now + timedelta(days=15)).strftime("%d.%m.%Y")

    if not driver.get("passport_number"):
        log.warning("poa.driver_passport_missing order=%s driver=%s",
                    order.id, order.driver_id)

    issued_at_raw = driver.get("passport_issued_at")
    passport_issued_at = ""
    if issued_at_raw:
        try:
            passport_issued_at = datetime.fromisoformat(str(issued_at_raw)).strftime("%d.%m.%Y")
        except ValueError:
            passport_issued_at = str(issued_at_raw)

    ctx = {
        "doc_number":          doc_number,
        "issued_at":           now_str,
        "valid_until":         valid_until,
        "seller":              seller or {},
        "buyer":               buyer,
        "driver_name":         driver.get("full_name") or "—",
        "passport_series":     driver.get("passport_series") or "",
        "passport_number":     driver.get("passport_number") or "",
        "passport_issued_by":  driver.get("passport_issued_by") or "",
        "passport_issued_at":  passport_issued_at,
        "fuel_name":           _fuel_name(order),
        "order_number":        order.order_number,
        "delivery_address":    order.delivery_address,
        "volume":              volume,
        "amount":              amount,
        "amount_in_words":     amount_to_words_ru(amount),
    }

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf,"poa.html", ctx)
        file_path = _save_pdf(order.id, doc_number, pdf_bytes)
        status = DocumentStatus.READY
    except Exception as exc:
        log.error("POA PDF render failed for order %s: %s", order.id, exc)
        file_path = None
        status = DocumentStatus.DRAFT

    doc = Document(
        order_id=order.id,
        doc_type=DocumentType.POA,
        doc_number=doc_number,
        status=status,
        seller_snapshot=seller or {},
        buyer_snapshot=buyer,
        issued_at=now,
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
    seller = await get_seller_snapshot(db)
    buyer  = await _fetch_buyer_snapshot(order)
    existing = await _existing_document(db, order.id, DocumentType.UPD)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.UPD)
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = _build_upd_ctx(
        doc_number=doc_number, issued_at=now_str,
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
    )

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf,"upd.html", ctx)
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
    buyer  = await _fetch_buyer_snapshot(order)
    existing = await _existing_document(db, order.id, DocumentType.INVOICE_PRELIMINARY)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.INVOICE_PRELIMINARY)
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = _build_invoice_ctx(
        doc_number=doc_number, issued_at=now_str,
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
        basis=f"Заявка №{order.order_number}",
    )

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf,"invoice.html", ctx)
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
    buyer  = await _fetch_buyer_snapshot(order)
    existing = await _existing_document(db, order.id, DocumentType.INVOICE_FINAL)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.INVOICE_FINAL)
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    ctx = _build_invoice_ctx(
        doc_number=doc_number, issued_at=now_str,
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
        basis=f"Заявка №{order.order_number}",
    )

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf,"invoice.html", ctx)
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


async def build_export_ctx(db: AsyncSession, doc: Document, order: Order) -> dict:
    """Восстановить контекст документа из сохранённого снимка для выгрузки в xlsx/docx.

    Использует СОХРАНЁННЫЕ значения (snapshot, суммы, номер, дата) — выгрузка
    совпадает с уже выпущенным PDF. order нужен для разбивки на позиции и
    адреса/топлива.
    """
    seller = doc.seller_snapshot or {}
    buyer = doc.buyer_snapshot or {}
    volume = float(doc.volume or order.volume_delivered or order.volume_requested or 0)
    total = float(doc.total_amount or 0)
    issued_at = doc.issued_at.strftime("%d.%m.%Y") if doc.issued_at else ""
    dtype = doc.doc_type.value if hasattr(doc.doc_type, "value") else str(doc.doc_type)

    if dtype in ("invoice", "invoice_preliminary", "invoice_final"):
        return _build_invoice_ctx(
            doc_number=doc.doc_number, issued_at=issued_at,
            seller=seller, buyer=buyer, order=order,
            volume=volume, total_amount=total,
            basis=f"Заявка №{order.order_number}",
        )
    if dtype == "upd":
        return _build_upd_ctx(
            doc_number=doc.doc_number, issued_at=issued_at,
            seller=seller, buyer=buyer, order=order,
            volume=volume, total_amount=total,
        )
    if dtype == "ttn":
        driver = await _fetch_driver_profile(order.driver_id)
        unit_price = round(total / volume, 2) if volume else 0.0
        return {
            "doc_number": doc.doc_number, "issued_at": issued_at,
            "seller": seller, "buyer": buyer,
            "fuel_name": _fuel_name(order), "order_number": order.order_number,
            "delivery_address": order.delivery_address,
            "volume": volume, "volume_delivered": volume, "unit_price": unit_price,
            "amount": total, "amount_in_words": amount_to_words_ru(total),
            "driver_name": driver.get("full_name") or "—",
        }
    if dtype == "poa":
        driver = await _fetch_driver_profile(order.driver_id)
        issued_dt = doc.issued_at or datetime.now(timezone.utc)
        issued_raw = driver.get("passport_issued_at")
        p_issued = ""
        if issued_raw:
            try:
                p_issued = datetime.fromisoformat(str(issued_raw)).strftime("%d.%m.%Y")
            except ValueError:
                p_issued = str(issued_raw)
        return {
            "doc_number": doc.doc_number, "issued_at": issued_at,
            "valid_until": (issued_dt + timedelta(days=15)).strftime("%d.%m.%Y"),
            "seller": seller, "buyer": buyer,
            "driver_name": driver.get("full_name") or "—",
            "passport_series": driver.get("passport_series") or "",
            "passport_number": driver.get("passport_number") or "",
            "passport_issued_by": driver.get("passport_issued_by") or "",
            "passport_issued_at": p_issued,
            "fuel_name": _fuel_name(order), "order_number": order.order_number,
            "delivery_address": order.delivery_address,
            "volume": volume, "amount": total,
            "amount_in_words": amount_to_words_ru(total),
        }
    raise ValidationError(f"Экспорт для типа «{dtype}» не поддерживается")


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
