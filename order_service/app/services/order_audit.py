"""CRM-44: журнал действий по заявке — «кто что сделал», только для админа.

Пишется из ключевых точек order_service/payment_service, читается одним
эндпоинтом GET /orders/{id}/audit. Запись в журнал никогда не должна ронять
основное действие: `record` только добавляет объект в сессию (без коммита),
а формулировки строятся уже при чтении.
"""
import enum
import logging
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenUser
from app.models.order_audit_log import OrderAuditLog

log = logging.getLogger(__name__)

# Виды действий
ACTION_CREATED = "order_created"
ACTION_FIELD = "field_changed"
ACTION_STATUS = "status_changed"
ACTION_PAYMENT = "payment_recorded"
ACTION_PAYMENT_CANCELLED = "payment_cancelled"

# Человеческие названия полей — те же ключи, что в OrderUpdateRequest.
FIELD_LABELS: dict[str, str] = {
    "fuel_type": "вид топлива",
    "volume_requested": "объём",
    "volume_delivered": "фактический объём",
    "delivery_address": "адрес доставки",
    "desired_date": "желаемую дату",
    "contact_person_name": "контактное лицо",
    "contact_person_phone": "телефон контакта",
    "client_comment": "комментарий клиента",
    "manager_comment": "комментарий менеджера",
    "manager_comment_internal": "комментарий менеджера",
    "driver_id": "водителя",
    "expected_amount": "ожидаемую сумму",
    "final_amount": "итоговую сумму",
    "delivery_cost": "стоимость доставки",
    "payment_type": "тип оплаты",
    "organization_id": "заказчика",
    "allow_delivery_unpaid": "доставку без оплаты",
    "trade_credit_contract_signed": "признак подписанного договора",
    "shipment_override": "разрешение отгрузки",
}

ROLE_LABELS: dict[str, str] = {
    "admin": "Администратор",
    "manager": "Менеджер",
    "driver": "Водитель",
    "client": "Клиент",
}

STATUS_LABELS: dict[str, str] = {
    "new": "новая",
    "awaiting_manager": "на согласовании",
    "accepted": "принята водителем",
    "delivered": "доставлена",
    "cancelled": "отменена",
}

# Единицы измерения для полей, где голое число нечитаемо
_FIELD_SUFFIX: dict[str, str] = {
    "volume_requested": " л",
    "volume_delivered": " л",
    "expected_amount": " ₽",
    "final_amount": " ₽",
    "delivery_cost": " ₽",
}


def stringify(value) -> str | None:
    """Привести значение поля к строке для журнала (None — как есть)."""
    if value is None:
        return None
    # str-энумы (PaymentType, OrderStatus) в 3.12 печатаются как «PaymentType.DEBT» —
    # в журнал кладём значение, иначе описание не прочитать.
    if isinstance(value, enum.Enum):
        value = value.value
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, (Decimal, float)):
        num = float(value)
        return str(int(num)) if num == int(num) else f"{num:.2f}"
    if isinstance(value, uuid.UUID):
        return str(value)
    text = str(value).strip()
    return text or None


def record(
    db: AsyncSession,
    order_id: uuid.UUID,
    actor: TokenUser | None,
    action: str,
    field: str | None = None,
    old_value=None,
    new_value=None,
) -> None:
    """Добавить запись в журнал (без commit — уедет с транзакцией действия)."""
    db.add(OrderAuditLog(
        order_id=order_id,
        actor_id=actor.id if actor else None,
        actor_role=actor.role if actor else None,
        action=action,
        field=field,
        old_value=stringify(old_value),
        new_value=stringify(new_value),
    ))


# Значения-коды, которые в журнале должны читаться по-русски
_VALUE_LABELS: dict[str, dict[str, str]] = {
    "payment_type": {
        "prepaid": "предоплата",
        "on_delivery": "по факту",
        "trade_credit": "товарный кредит",
        "postpaid": "постоплата",
        "debt": "в долг",
    },
}


def _fmt(field: str | None, value: str | None) -> str:
    if value is None or value == "":
        return "пусто"
    labels = _VALUE_LABELS.get(field or "", {})
    value = labels.get(value, value)
    return f"{value}{_FIELD_SUFFIX.get(field or '', '')}"


def describe(entry: OrderAuditLog, actor_name: str | None) -> str:
    """Русская формулировка записи: «Сомов изменил объём 3000 л → 2800 л»."""
    who = actor_name or ROLE_LABELS.get(entry.actor_role or "", "Пользователь")

    if entry.action == ACTION_CREATED:
        return f"{who} создал(а) заявку"
    if entry.action == ACTION_STATUS:
        to_label = STATUS_LABELS.get(entry.new_value or "", entry.new_value or "")
        if entry.new_value == "delivered":
            return f"{who} отметил(а) заявку доставленной"
        if entry.new_value == "cancelled":
            return f"{who} отменил(а) заявку"
        return f"{who} перевёл(а) заявку в статус «{to_label}»"
    if entry.action == ACTION_PAYMENT:
        method = f" ({entry.field})" if entry.field else ""
        return f"{who} отметил(а) оплату получена: {_fmt('final_amount', entry.new_value)}{method}"
    if entry.action == ACTION_PAYMENT_CANCELLED:
        return f"{who} отменил(а) оплату {_fmt('final_amount', entry.old_value)}"

    label = FIELD_LABELS.get(entry.field or "", entry.field or "поле")
    if entry.old_value is None and entry.new_value is not None:
        return f"{who} добавил(а) {label}: {_fmt(entry.field, entry.new_value)}"
    if entry.new_value is None and entry.old_value is not None:
        return f"{who} очистил(а) {label} (было {_fmt(entry.field, entry.old_value)})"
    return (
        f"{who} изменил(а) {label} "
        f"{_fmt(entry.field, entry.old_value)} → {_fmt(entry.field, entry.new_value)}"
    )


async def list_for_order(db: AsyncSession, order_id: uuid.UUID) -> list[OrderAuditLog]:
    result = await db.execute(
        select(OrderAuditLog)
        .where(OrderAuditLog.order_id == order_id)
        .order_by(OrderAuditLog.created_at.desc())
    )
    return list(result.scalars().all())
