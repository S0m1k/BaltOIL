"""
Dev seed for order_service: creates orders and payments.
FORBIDDEN on production (APP_ENV=production).
Run via: docker compose exec order_service python /app/scripts/seed.py
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

if os.environ.get("APP_ENV") == "production":
    print("ERROR: seed.py is FORBIDDEN on production", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

sys.path.insert(0, "/app")

from app.config import get_settings
from app.models import Order, OrderStatus, OrderKind, PaymentType, OrderStatusLog, OrderKindCounter
from app.models import Payment, PaymentStatus, PaymentMethod, PaymentKind
from app.models import LegalEntity

settings = get_settings()

# Same fixed UUIDs as auth seed
USERS = {
    "manager1":    uuid.UUID("00000000-0000-0000-0000-000000000002"),
    "manager2":    uuid.UUID("00000000-0000-0000-0000-000000000003"),
    "driver1":     uuid.UUID("00000000-0000-0000-0000-000000000004"),
    "driver2":     uuid.UUID("00000000-0000-0000-0000-000000000005"),
    "client_pre":  uuid.UUID("00000000-0000-0000-0000-000000000011"),
    "client_del":  uuid.UUID("00000000-0000-0000-0000-000000000012"),
    "client_tc":   uuid.UUID("00000000-0000-0000-0000-000000000013"),
    "client_post": uuid.UUID("00000000-0000-0000-0000-000000000014"),
    "client_mix":  uuid.UUID("00000000-0000-0000-0000-000000000015"),
}

now = datetime.now(timezone.utc)

# Fixed order UUIDs for idempotent cleanup
ORDER_IDS = {f"ord_{i}": uuid.UUID(f"10000000-0000-0000-0000-{i:012d}") for i in range(1, 11)}

ORDERS = [
    # 1. NEW — физлицо, предоплата
    dict(
        id=ORDER_IDS["ord_1"], order_number="ф1", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_pre"], manager_id=USERS["manager1"],
        fuel_type="diesel_summer", volume_requested=Decimal("5000"),
        delivery_address="г. Москва, ул. Тестовая, 1",
        payment_type=PaymentType.PREPAID, expected_amount=Decimal("95000"),
        status=OrderStatus.NEW, payment_status="unpaid",
        desired_date=now + timedelta(days=2),
    ),
    # 2. NEW — физлицо, on_delivery (пул водителей)
    dict(
        id=ORDER_IDS["ord_2"], order_number="ф2", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_del"], manager_id=None,
        fuel_type="petrol_95", volume_requested=Decimal("2000"),
        delivery_address="г. Москва, пр. Мира, 42",
        payment_type=PaymentType.ON_DELIVERY,
        status=OrderStatus.NEW, payment_status="unpaid",
    ),
    # 3. ACCEPTED — юрлицо, trade_credit (водитель взял)
    dict(
        id=ORDER_IDS["ord_3"], order_number="ю1", order_kind=OrderKind.COMPANY,
        client_id=USERS["client_tc"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type="diesel_winter", volume_requested=Decimal("10000"),
        delivery_address="г. Москва, ул. Ленина, 10",
        payment_type=PaymentType.TRADE_CREDIT, trade_credit_contract_signed=True,
        status=OrderStatus.ACCEPTED, payment_status="unpaid",
    ),
    # 4. ACCEPTED — физлицо, postpaid (водитель взял)
    dict(
        id=ORDER_IDS["ord_4"], order_number="ф3", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_mix"], manager_id=USERS["manager2"], driver_id=USERS["driver2"],
        fuel_type="petrol_92", volume_requested=Decimal("3000"),
        delivery_address="г. Москва, Лесная ул., 25",
        payment_type=PaymentType.POSTPAID, expected_amount=Decimal("90000"),
        status=OrderStatus.ACCEPTED, payment_status="partially_paid",
    ),
    # 5. ACCEPTED — физлицо, prepaid, оплачена (бывш. in_transit → accepted)
    dict(
        id=ORDER_IDS["ord_5"], order_number="ф4", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_pre"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type="diesel_summer", volume_requested=Decimal("8000"),
        delivery_address="г. Москва, ул. Тестовая, 1",
        payment_type=PaymentType.PREPAID, expected_amount=Decimal("120000"),
        status=OrderStatus.ACCEPTED, payment_status="paid",
    ),
    # 6. DELIVERED — физлицо, on_delivery, оплачена
    dict(
        id=ORDER_IDS["ord_6"], order_number="ф5", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_del"], manager_id=USERS["manager2"], driver_id=USERS["driver2"],
        fuel_type="petrol_95", volume_requested=Decimal("2000"), volume_delivered=Decimal("2000"),
        delivery_address="г. Москва, пр. Мира, 42",
        payment_type=PaymentType.ON_DELIVERY, final_amount=Decimal("56000"),
        status=OrderStatus.DELIVERED, payment_status="paid", ttn_number="ТТН-000056",
    ),
    # 7. DELIVERED — физлицо, postpaid, не оплачена (ждёт оплаты)
    dict(
        id=ORDER_IDS["ord_7"], order_number="ф6", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_post"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type="diesel_winter", volume_requested=Decimal("6000"), volume_delivered=Decimal("6000"),
        delivery_address="г. Москва, ул. Садовая, 7",
        payment_type=PaymentType.POSTPAID, final_amount=Decimal("126000"),
        status=OrderStatus.DELIVERED, payment_status="unpaid", ttn_number="ТТН-000126",
    ),
    # 8. ACCEPTED — физлицо, prepaid (бывш. partially_delivered → accepted)
    dict(
        id=ORDER_IDS["ord_8"], order_number="ф7", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_pre"], manager_id=USERS["manager2"], driver_id=USERS["driver2"],
        fuel_type="petrol_92", volume_requested=Decimal("5000"),
        delivery_address="г. Москва, ул. Тестовая, 1",
        payment_type=PaymentType.PREPAID, expected_amount=Decimal("100000"),
        status=OrderStatus.ACCEPTED, payment_status="paid",
    ),
    # 9. DELIVERED — юрлицо, trade_credit, оплачена (бывш. closed → delivered)
    dict(
        id=ORDER_IDS["ord_9"], order_number="ю2", order_kind=OrderKind.COMPANY,
        client_id=USERS["client_tc"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type="diesel_summer", volume_requested=Decimal("15000"), volume_delivered=Decimal("15000"),
        delivery_address="г. Москва, ул. Ленина, 10",
        payment_type=PaymentType.TRADE_CREDIT, trade_credit_contract_signed=True,
        expected_amount=Decimal("315000"), final_amount=Decimal("315000"),
        status=OrderStatus.DELIVERED, payment_status="paid", ttn_number="ТТН-000315",
    ),
    # 10. CANCELLED — физлицо (бывш. rejected → cancelled)
    dict(
        id=ORDER_IDS["ord_10"], order_number="ф8", order_kind=OrderKind.INDIVIDUAL,
        client_id=USERS["client_del"], manager_id=USERS["manager2"],
        fuel_type="fuel_oil", volume_requested=Decimal("20000"),
        delivery_address="г. Москва, пр. Мира, 42",
        payment_type=PaymentType.ON_DELIVERY, status=OrderStatus.CANCELLED,
        payment_status="unpaid",
        rejection_reason="Недостаточный запас топлива. Обратитесь позже.",
    ),
]

# Payments for relevant orders
PAYMENT_IDS = {f"pay_{i}": uuid.UUID(f"20000000-0000-0000-0000-{i:012d}") for i in range(1, 8)}

PAYMENTS = [
    # ord_4: partial payment
    dict(id=PAYMENT_IDS["pay_1"], order_id=ORDER_IDS["ord_4"], client_id=USERS["client_mix"],
         kind=PaymentKind.PREPAYMENT, status=PaymentStatus.PAID, method=PaymentMethod.BANK_TRANSFER,
         amount=Decimal("45000"), paid_at=now - timedelta(days=2), created_by_id=USERS["manager2"],
         notes="Частичная предоплата 50%"),
    # ord_5: full payment upfront
    dict(id=PAYMENT_IDS["pay_2"], order_id=ORDER_IDS["ord_5"], client_id=USERS["client_pre"],
         kind=PaymentKind.PREPAYMENT, status=PaymentStatus.PAID, method=PaymentMethod.BANK_TRANSFER,
         amount=Decimal("120000"), paid_at=now - timedelta(days=3), created_by_id=USERS["manager1"]),
    # ord_6: paid on delivery
    dict(id=PAYMENT_IDS["pay_3"], order_id=ORDER_IDS["ord_6"], client_id=USERS["client_del"],
         kind=PaymentKind.ACTUAL, status=PaymentStatus.PAID, method=PaymentMethod.CASH,
         amount=Decimal("56000"), paid_at=now - timedelta(hours=6), created_by_id=USERS["driver2"]),
    # ord_8: prepayment
    dict(id=PAYMENT_IDS["pay_4"], order_id=ORDER_IDS["ord_8"], client_id=USERS["client_pre"],
         kind=PaymentKind.PREPAYMENT, status=PaymentStatus.PAID, method=PaymentMethod.BANK_TRANSFER,
         amount=Decimal("100000"), paid_at=now - timedelta(days=5), created_by_id=USERS["manager2"],
         notes="Предоплата по плановому объёму"),
    # ord_9: delivered, fully paid
    dict(id=PAYMENT_IDS["pay_5"], order_id=ORDER_IDS["ord_9"], client_id=USERS["client_tc"],
         kind=PaymentKind.INVOICE, status=PaymentStatus.PAID, method=PaymentMethod.BANK_TRANSFER,
         amount=Decimal("315000"), paid_at=now - timedelta(days=10), created_by_id=USERS["manager1"]),
]


async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Wipe existing seed data by known UUIDs
        order_ids = list(ORDER_IDS.values())
        payment_ids = list(PAYMENT_IDS.values())
        await session.execute(text("DELETE FROM payments WHERE id = ANY(:ids)"), {"ids": payment_ids})
        await session.execute(text("DELETE FROM order_status_logs WHERE order_id = ANY(:ids)"), {"ids": order_ids})
        await session.execute(text("DELETE FROM orders WHERE id = ANY(:ids)"), {"ids": order_ids})
        await session.execute(text("DELETE FROM order_kind_counters"))
        # Сброс реквизитов юр. лица (seed добавит актуальную версию)
        await session.execute(text("DELETE FROM legal_entities"))
        await session.commit()

        # Реквизиты юридического лица (тестовые)
        session.add(LegalEntity(
            name='ООО "Северо-Западная Топливная Компания"',
            short_name="ООО СЗТК",
            inn="7811123456",
            kpp="781101001",
            ogrn="1027800000001",
            bank_name="ПАО Сбербанк",
            bik="044030653",
            checking_account="40702810900000000001",
            correspondent_account="30101810400000000225",
            legal_address="190000, г. Санкт-Петербург, Лиговский пр., д. 1, офис 1",
            phone="+7 (812) 917-15-17",
            email="sz_tk@mail.ru",
            director_name="Иванов Иван Иванович",
            director_title="Генеральный директор",
            is_active=True,
        ))
        await session.commit()

        # Per-kind counters (соответствуют выданным номерам ф1..ф8 / ю1..ю2)
        session.add(OrderKindCounter(kind=OrderKind.INDIVIDUAL.value, last_seq=8))
        session.add(OrderKindCounter(kind=OrderKind.COMPANY.value, last_seq=2))

        # Orders
        for o in ORDERS:
            o.setdefault("driver_id", None)
            o.setdefault("volume_delivered", None)
            o.setdefault("desired_date", None)
            o.setdefault("client_comment", None)
            o.setdefault("manager_comment", None)
            o.setdefault("rejection_reason", None)
            o.setdefault("expected_amount", None)
            o.setdefault("final_amount", None)
            o.setdefault("ttn_number", None)
            o.setdefault("trade_credit_contract_signed", False)
            session.add(Order(**o))
        await session.commit()

        # Payments
        for p in PAYMENTS:
            p.setdefault("paid_at", None)
            p.setdefault("notes", None)
            p.setdefault("invoice_number", None)
            session.add(Payment(**p))
        await session.commit()

    await engine.dispose()
    print(f"[seed:orders] Created legal_entity, {len(ORDERS)} orders, {len(PAYMENTS)} payments")


if __name__ == "__main__":
    asyncio.run(main())
