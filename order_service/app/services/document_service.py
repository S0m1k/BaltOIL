"""
Генерация документов (счёт, ТТН, УПД) в PDF через WeasyPrint + Jinja2.

Файлы сохраняются в /app/media/documents/{order_id}/{doc_number}.pdf.
Путь записывается в Document.file_path для последующей отдачи клиенту.
"""
import asyncio
import base64
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

import httpx

from app.config import settings
from app.core.media import resolve_media_path
from app.models.document import Document, DocumentType, DocumentStatus, DocNumberCounter
from app.models.order import Order
from app.models.payment import Payment, PaymentStatus
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

# ── Факсимиле (подпись/печать продавца) — читаются с диска, без миграции БД ────

def _legal_image_data_uri(filename: str) -> str | None:
    """Прочитать факсимиле из MEDIA_ROOT/legal и вернуть как data: URI для PDF."""
    path = MEDIA_ROOT / "legal" / filename
    if not path.exists():
        return None
    data = path.read_bytes()
    mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def seller_signature_data_uri() -> str | None:
    return _legal_image_data_uri("signature.png")


def seller_stamp_data_uri() -> str | None:
    return _legal_image_data_uri("stamp.png")


def _short_sign_name(full_name: str | None) -> str:
    """'Борзяев Дмитрий Геннадьевич' → 'Борзяев Д.Г.' (для расшифровки подписи)."""
    if not full_name:
        return "________________"
    parts = full_name.split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}.{parts[2][0]}."
    if len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return full_name


FUEL_LABELS = {
    "diesel_summer": "Дизельное топливо летнее (ДТ-Л)",
    "diesel_winter": "Дизельное топливо зимнее (ДТ-З)",
    "petrol_92":     "Бензин АИ-92",
    "petrol_95":     "Бензин АИ-95",
    "fuel_oil":      "Топочный мазут М-100",
}


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

_INVOICE_DOC_TYPE_VALUES = {"invoice", "invoice_preliminary", "invoice_final"}

# Сквозной счётчик-ключ для счётов (без года) — клиент хочет простые 4-значные
# номера ("0145", "0146"...), а не "INV-2026-000069". TTN/УПД/доверенность —
# нумерация по-прежнему по (префикс, год), без изменений.
_INVOICE_COUNTER_KEY = "INV"


async def _next_doc_number(db: AsyncSession, doc_type: DocumentType) -> str:
    """Сгенерировать номер документа.

    Счета (invoice/invoice_preliminary/invoice_final) — сквозной 4-значный номер
    вида "0145" (без года, без префикса), отдельный счётчик с prefix_key="INV".
    ТТН/УПД/доверенность — прежняя схема "TTN-2026-000001" по (префикс, год).

    Атомарно через DocNumberCounter (INSERT ... ON CONFLICT DO UPDATE ... RETURNING) —
    как нумерация заказов/договоров. Прежний COUNT(*)+1 давал гонки: две одновременные
    доставки получали один номер → IntegrityError на flush внутри транзакции перехода.
    """
    if doc_type.value in _INVOICE_DOC_TYPE_VALUES:
        stmt = (
            pg_insert(DocNumberCounter)
            .values(prefix_key=_INVOICE_COUNTER_KEY, last_seq=1)
            .on_conflict_do_update(
                index_elements=["prefix_key"],
                set_={"last_seq": DocNumberCounter.last_seq + 1},
            )
            .returning(DocNumberCounter.last_seq)
        )
        seq: int = (await db.execute(stmt)).scalar_one()
        return f"{seq:04d}"

    prefix = {
        "ttn": "TTN",
        "upd": "UPD",
        "poa": "POA",
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
    seq2: int = (await db.execute(stmt)).scalar_one()
    return f"{prefix}-{year}-{seq2:06d}"


async def _existing_document(
    db: AsyncSession, order_id: uuid.UUID, doc_type: DocumentType
) -> Document | None:
    """Уже выпущенный (не аннулированный) документ этого типа по заявке — для идемпотентности.

    Идемпотентность: если документ уже выпущен (не аннулирован), возвращаем его
    вместо создания дубля с новым номером.
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


def _order_amount(order: Order) -> float:
    """Сумма заявки для документа — из тарифных полей (final/expected_amount).

    Эти суммы рассчитываются по тарифу клиента при создании/доставке. Если тариф
    не настроен и сумма не рассчитана — документ не формируется (fail loud),
    чтобы не выпустить документ с неверной ценой."""
    if order.final_amount is not None:
        return float(order.final_amount)
    if order.expected_amount is not None:
        return float(order.expected_amount)
    raise ValidationError(
        "Сумма заявки не рассчитана — не настроен тариф для этого вида топлива "
        "или клиента. Документ не может быть сформирован с неверной суммой."
    )


# ── Invoice context (по образцу заказчика) ────────────────────────────────────

# Дефолтная ставка НДС, если в seller-снимке не указано. Образец заказчика —
# 22%. Когда в LegalEntity появится поле vat_rate, использовать оттуда.
DEFAULT_VAT_RATE = 22


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
        "seller_signature": seller_signature_data_uri(),
        "seller_stamp":      seller_stamp_data_uri(),
        "seller_sign_name":  _short_sign_name((seller or {}).get("director_name")),
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
    """Разбить заказ на позиции (только топливо) с разбивкой НДС.

    total_amount — сумма С НДС (то, что клиент платит, как order.expected/final_amount,
    на этой сумме строится учёт долга). В образце счёта строки и «Итого» показаны
    БЕЗ НДС, НДС добавляется отдельной строкой, «Всего к оплате» = с НДС. Поэтому
    раскладываем total_amount обратно на пред-НДС базу и налог.

    Стоимость доставки уже включена в total_amount (Д3) и отдельной строкой не
    выводится — вся пред-НДС база ложится на единственную строку топлива.

    Возвращает (items, subtotal_no_vat, vat_amount, total), где total == total_amount.
    """
    rate = vat_rate or 0
    pre_vat_total = round(total_amount / (1 + rate / 100), 2) if rate else total_amount

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

    items = [_line(_fuel_name(order), volume, "л", "112", pre_vat_total)]

    subtotal_no_vat = round(sum(i["sum_no_vat"] for i in items), 2)
    # Налог считаем как разницу, чтобы «Всего» точно совпало с total_amount (учёт долга).
    vat_amount = round(total_amount - subtotal_no_vat, 2)
    # Согласуем построчный НДС с итоговым: остаток округления вешаем на последнюю
    # строку, иначе сумма столбцов «НДС»/«Сумма с НДС» по строкам могла на копейку
    # не совпасть с итоговой строкой (бухгалтер расценит как ошибку документа).
    line_vat_sum = round(sum(i["vat"] for i in items), 2)
    residual = round(vat_amount - line_vat_sum, 2)
    if residual and items:
        items[-1]["vat"] = round(items[-1]["vat"] + residual, 2)
        items[-1]["sum"] = round(items[-1]["sum_no_vat"] + items[-1]["vat"], 2)
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
    # Для заявки от организации — реквизиты организации, иначе физлица.
    params = (
        {"organization_id": str(order.organization_id)} if order.organization_id else None
    )
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{base}/api/v1/internal/clients/{order.client_id}/buyer-snapshot",
                params=params,
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


# ── Основание счёта ───────────────────────────────────────────────────────────

async def _invoice_basis(db: AsyncSession, order: Order, doc_type: DocumentType) -> str:
    """«Основание» счёта: «Договор о поставке Нефтепродуктов № {N} от «дд.мм.гггг»».

    Номер и дата договора — из активного договора клиента/организации (если есть).
    Источник даты для договора — дата его подписания (signed_at). Если активного
    договора нет — fallback на прежнее поведение (только дата, без номера):
      - предварительный счёт → дата создания заявки;
      - финальный счёт → дата последней проведённой оплаты (fallback — текущий
        момент, т.е. дата доставки: финальный счёт выпускается при переходе
        в DELIVERED).
    """
    from app.services.contract_service import get_active_contract  # локальный импорт — без цикла

    contract = await get_active_contract(db, order.client_id, order.organization_id)
    if contract is not None and contract.signed_at:
        date_str = contract.signed_at.strftime("%d.%m.%Y")
        return f"Договор о поставке Нефтепродуктов № {contract.contract_number} от «{date_str}»"

    if doc_type == DocumentType.INVOICE_FINAL:
        result = await db.execute(
            select(Payment.paid_at)
            .where(
                Payment.order_id == order.id,
                Payment.status == PaymentStatus.PAID,
                Payment.paid_at.is_not(None),
            )
            .order_by(Payment.paid_at.desc())
            .limit(1)
        )
        basis_dt = result.scalar_one_or_none() or datetime.now(timezone.utc)
    else:
        basis_dt = order.created_at or datetime.now(timezone.utc)
    date_str = basis_dt.strftime("%d.%m.%Y")
    return f"Договор о поставке Нефтепродуктов от «{date_str}»"


# ── Public API ────────────────────────────────────────────────────────────────

async def generate_ttn(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
    driver_name: str = "—",
) -> Document:
    """Сформировать ТТН по факту доставки (DELIVERED)."""
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order)
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

    Паспорт водителя тянем из auth_service;
    если не заполнен/водитель не назначен — в PDF прочерк, в логе warning.
    """
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order)
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
    amount = _order_amount(order)
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
    amount = _order_amount(order)
    seller = await get_seller_snapshot(db)
    buyer  = await _fetch_buyer_snapshot(order)
    existing = await _existing_document(db, order.id, DocumentType.INVOICE_PRELIMINARY)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.INVOICE_PRELIMINARY)
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    basis = await _invoice_basis(db, order, DocumentType.INVOICE_PRELIMINARY)
    ctx = _build_invoice_ctx(
        doc_number=doc_number, issued_at=now_str,
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
        basis=basis,
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
    """Финальный счёт — выпускается при переходе в DELIVERED."""
    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order)
    seller = await get_seller_snapshot(db)
    buyer  = await _fetch_buyer_snapshot(order)
    existing = await _existing_document(db, order.id, DocumentType.INVOICE_FINAL)
    if existing:
        return existing
    doc_number = await _next_doc_number(db, DocumentType.INVOICE_FINAL)
    now_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    basis = await _invoice_basis(db, order, DocumentType.INVOICE_FINAL)
    ctx = _build_invoice_ctx(
        doc_number=doc_number, issued_at=now_str,
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
        basis=basis,
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


async def generate_invoice(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
) -> Document:
    """Единый счёт по заявке (Д4 2026-06-23: один счёт вместо предв./финального).

    Идемпотентно: если активный счёт уже выпущен — возвращаем его. Для обновления
    сумм/объёма после правок используйте regenerate_invoice (тот же номер)."""
    existing = await _existing_document(db, order.id, DocumentType.INVOICE)
    if existing:
        return existing

    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order)
    seller = await get_seller_snapshot(db)
    buyer  = await _fetch_buyer_snapshot(order)
    doc_number = await _next_doc_number(db, DocumentType.INVOICE)
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%d.%m.%Y")
    basis = await _invoice_basis(db, order, DocumentType.INVOICE)
    ctx = _build_invoice_ctx(
        doc_number=doc_number, issued_at=now_str,
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
        basis=basis,
    )

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf, "invoice.html", ctx)
        file_path = _save_pdf(order.id, doc_number, pdf_bytes)
        status = DocumentStatus.READY
    except Exception as exc:
        log.error("Invoice PDF render failed for order %s: %s", order.id, exc)
        file_path = None
        status = DocumentStatus.DRAFT

    doc = Document(
        order_id=order.id,
        doc_type=DocumentType.INVOICE,
        doc_number=doc_number,
        status=status,
        seller_snapshot=seller,
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


async def regenerate_invoice(
    db: AsyncSession,
    order: Order,
    actor: TokenUser,
) -> Document:
    """Перевыпустить единый счёт с актуальными суммами/объёмом, СОХРАНИВ номер.

    Вызывается после правок заявки админом (объём, стоимость доставки, сумма)
    и при доставке (фактический объём). Если счёта ещё нет — создаёт новый.
    Снимок реквизитов обновляется на текущий, PDF перерисовывается на месте.
    """
    existing = await _existing_document(db, order.id, DocumentType.INVOICE)
    if existing is None:
        return await generate_invoice(db, order, actor)

    volume = float(order.volume_delivered or order.volume_requested)
    amount = _order_amount(order)
    seller = await get_seller_snapshot(db)
    buyer  = await _fetch_buyer_snapshot(order)
    issued_at = existing.issued_at or datetime.now(timezone.utc)
    basis = await _invoice_basis(db, order, DocumentType.INVOICE)
    ctx = _build_invoice_ctx(
        doc_number=existing.doc_number,
        issued_at=issued_at.strftime("%d.%m.%Y"),
        seller=seller, buyer=buyer, order=order,
        volume=volume, total_amount=amount,
        basis=basis,
    )

    try:
        pdf_bytes = await asyncio.to_thread(_render_pdf, "invoice.html", ctx)
        file_path = _save_pdf(order.id, existing.doc_number, pdf_bytes)
        existing.file_path = file_path
        existing.status = DocumentStatus.READY
    except Exception as exc:
        log.error("Invoice PDF re-render failed for order %s: %s", order.id, exc)
        # Оставляем прежний файл/статус — лучше старый корректный PDF, чем пустой.

    existing.seller_snapshot = seller
    existing.buyer_snapshot = buyer
    existing.total_amount = amount
    existing.volume = volume
    await db.flush()
    return existing


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
        basis = await _invoice_basis(db, order, doc.doc_type)
        return _build_invoice_ctx(
            doc_number=doc.doc_number, issued_at=issued_at,
            seller=seller, buyer=buyer, order=order,
            volume=volume, total_amount=total,
            basis=basis,
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


# ── Отправка документа клиенту (чат/email) ──────────────────────────────────────
# Вынесено из routers/documents.py (правка 2026-06-24), чтобы переиспользовать
# из автоматики (счёт ≤3000 л для юрлица при создании заявки) и из ручных
# эндпоинтов send/send-email без дублирования логики.

_DOC_TYPE_LABELS_RU = {
    "invoice": "Счёт",
    "invoice_preliminary": "Счёт",
    "invoice_final": "Счёт",
    "ttn": "ТТН",
    "upd": "УПД",
}


async def send_document_to_chat(
    db: AsyncSession, order: Order, doc: Document, actor_token: str,
) -> dict:
    """Отправить документ в чат по заявке (диалог клиент↔менеджер).

    Находит или создаёт диалог заявки, отправляет сообщение типа 'document',
    обновляет статус документа на SENT. `actor_token` — JWT вызывающего
    (менеджера/админа или служебный токен) для авторизации в chat_service.
    """
    if doc.status == DocumentStatus.DRAFT:
        raise ValidationError("PDF ещё не сгенерирован (статус DRAFT). Дождитесь генерации.")

    base = settings.chat_service_url.rstrip("/")
    headers = {"Authorization": f"Bearer {actor_token}"}

    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            f"{base}/api/v1/conversations",
            params={"order_id": str(order.id)},
            headers=headers,
        )
        r.raise_for_status()
        convs = r.json()

        if convs:
            conv_id = convs[0]["id"]
        else:
            r2 = await client.post(
                f"{base}/api/v1/conversations/ensure-client-manager",
                json={"client_id": str(order.client_id)},
                headers=headers,
            )
            r2.raise_for_status()
            conv_id = r2.json()["id"]

        doc_type_value = doc.doc_type.value if hasattr(doc.doc_type, "value") else doc.doc_type
        doc_type_label = _DOC_TYPE_LABELS_RU.get(doc_type_value, "Документ")
        msg_text = f"📄 {doc_type_label} {doc.doc_number} по заявке {order.order_number}"

        r3 = await client.post(
            f"{base}/api/v1/conversations/{conv_id}/messages",
            json={
                "text": msg_text,
                "msg_type": "document",
                "metadata": {
                    "document_id": str(doc.id),
                    "doc_number": doc.doc_number,
                    "doc_type": doc_type_value,
                    "order_id": str(order.id),
                    "order_number": order.order_number,
                    "download_path": f"/api/v1/orders/{order.id}/documents/{doc.id}/download",
                },
            },
            headers=headers,
        )
        r3.raise_for_status()

    doc.status = DocumentStatus.SENT
    await db.flush()

    return {"ok": True, "conv_id": conv_id}


async def send_document_by_email(db: AsyncSession, order: Order, doc: Document) -> dict:
    """Отправить PDF документа клиенту на email.

    Адрес получателя берётся ТОЛЬКО из профиля клиента заявки (billing_email
    или user.email через auth_service) — без override снаружи, чтобы документы
    нельзя было отправить на произвольный адрес.
    """
    if doc.status not in (DocumentStatus.READY, DocumentStatus.SENT):
        raise ValidationError("document not ready")
    if not doc.file_path:
        raise NotFoundError("document file missing")

    full_path = resolve_media_path(MEDIA_ROOT, doc.file_path)
    if not full_path.exists():
        raise NotFoundError("document file missing")

    auth_base = settings.auth_service_url.rstrip("/")
    internal_headers = {"X-Internal-Secret": settings.internal_api_secret}
    recipient = None
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Заявка на организацию → сначала почта для счетов самой организации
        # (правки 2026-07-22). Важно для «ничейных» организаций, где
        # order.client_id — сотрудник, а не клиент.
        if order.organization_id:
            r0 = await client.get(
                f"{auth_base}/api/v1/internal/organizations/{order.organization_id}/contract-target",
                headers=internal_headers,
            )
            if r0.status_code == 200:
                recipient = r0.json().get("billing_email")
        if not recipient:
            r = await client.get(
                f"{auth_base}/api/v1/internal/users/{order.client_id}/email-target",
                headers=internal_headers,
            )
            r.raise_for_status()
            recipient = r.json().get("email")

    if not recipient:
        raise ValidationError("recipient has no email")

    pdf_bytes = full_path.read_bytes()
    content_b64 = base64.b64encode(pdf_bytes).decode()

    subject = f"Документ {doc.doc_number} по заявке {order.order_number}"
    body_text = (
        "Здравствуйте,\n\n"
        "Во вложении документ по вашей заявке.\n\n"
        "— СЗТК"
    )
    filename = f"{doc.doc_number}.pdf"

    notif_base = settings.notification_service_url.rstrip("/")
    sent = False
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

    if not sent:
        raise ValidationError("email service unavailable")

    doc.status = DocumentStatus.SENT
    await db.flush()

    log.info(
        "document.sent_email action document_id=%s order_id=%s to=%s filename=%s",
        doc.id, order.id, recipient, filename,
    )

    return {"ok": True, "to": recipient}
