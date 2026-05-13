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
from app.models import Order, OrderStatus, FuelType, PaymentType, OrderPriority, OrderStatusLog, OrderYearCounter
from app.models import Payment, PaymentStatus, PaymentMethod, PaymentKind

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
    # 1. NEW — prepaid client, предоплата
    dict(
        id=ORDER_IDS["ord_1"], order_number="ORD-2026-000001",
        client_id=USERS["client_pre"], manager_id=USERS["manager1"],
        fuel_type=FuelType.DIESEL_SUMMER, volume_requested=Decimal("5000"),
        delivery_address="г. Москва, ул. Тестовая, 1",
        payment_type=PaymentType.INVOICE, status=OrderStatus.NEW,
        payment_status="unpaid", priority=OrderPriority.NORMAL,
        desired_date=now + timedelta(days=2),
    ),
    # 2. NEW — urgent
    dict(
        id=ORDER_IDS["ord_2"], order_number="ORD-2026-000002",
        client_id=USERS["client_del"], manager_id=None,
        fuel_type=FuelType.PETROL_95, volume_requested=Decimal("2000"),
        delivery_address="г. Москва, пр. Мира, 42",
        payment_type=PaymentType.ON_DELIVERY, status=OrderStatus.NEW,
        payment_status="unpaid", priority=OrderPriority.URGENT,
    ),
    # 3. IN_PROGRESS
    dict(
        id=ORDER_IDS["ord_3"], order_number="ORD-2026-000003",
        client_id=USERS["client_tc"], manager_id=USERS["manager1"],
        fuel_type=FuelType.DIESEL_WINTER, volume_requested=Decimal("10000"),
        delivery_address="г. Москва, ул. Ленина, 10",
        payment_type=PaymentType.INVOICE, status=OrderStatus.IN_PROGRESS,
        payment_status="unpaid", priority=OrderPriority.NORMAL,
    ),
    # 4. IN_PROGRESS — partially paid
    dict(
        id=ORDER_IDS["ord_4"], order_number="ORD-2026-000004",
        client_id=USERS["client_mix"], manager_id=USERS["manager2"],
        fuel_type=FuelType.PETROL_92, volume_requested=Decimal("3000"),
        delivery_address="г. Москва, Лесная ул., 25",
        payment_type=PaymentType.INVOICE, status=OrderStatus.IN_PROGRESS,
        payment_status="partially_paid", priority=OrderPriority.NORMAL,
    ),
    # 5. IN_TRANSIT
    dict(
        id=ORDER_IDS["ord_5"], order_number="ORD-2026-000005",
        client_id=USERS["client_pre"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type=FuelType.DIESEL_SUMMER, volume_requested=Decimal("8000"),
        delivery_address="г. Москва, ул. Тестовая, 1",
        payment_type=PaymentType.INVOICE, status=OrderStatus.IN_TRANSIT,
        payment_status="paid", priority=OrderPriority.NORMAL,
    ),
    # 6. DELIVERED — fully paid (can be closed)
    dict(
        id=ORDER_IDS["ord_6"], order_number="ORD-2026-000006",
        client_id=USERS["client_del"], manager_id=USERS["manager2"], driver_id=USERS["driver2"],
        fuel_type=FuelType.PETROL_95, volume_requested=Decimal("2000"), volume_delivered=Decimal("2000"),
        delivery_address="г. Москва, пр. Мира, 42",
        payment_type=PaymentType.ON_DELIVERY, status=OrderStatus.DELIVERED,
        payment_status="paid", priority=OrderPriority.NORMAL,
    ),
    # 7. DELIVERED — unpaid (awaiting payment — cannot be closed)
    dict(
        id=ORDER_IDS["ord_7"], order_number="ORD-2026-000007",
        client_id=USERS["client_post"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type=FuelType.DIESEL_WINTER, volume_requested=Decimal("6000"), volume_delivered=Decimal("6000"),
        delivery_address="г. Москва, ул. Садовая, 7",
        payment_type=PaymentType.INVOICE, status=OrderStatus.DELIVERED,
        payment_status="unpaid", priority=OrderPriority.NORMAL,
    ),
    # 8. PARTIALLY_DELIVERED — overpaid (client paid 100k, delivered less = 80k)
    dict(
        id=ORDER_IDS["ord_8"], order_number="ORD-2026-000008",
        client_id=USERS["client_pre"], manager_id=USERS["manager2"], driver_id=USERS["driver2"],
        fuel_type=FuelType.PETROL_92, volume_requested=Decimal("5000"), volume_delivered=Decimal("4000"),
        delivery_address="г. Москва, ул. Тестовая, 1",
        payment_type=PaymentType.INVOICE, status=OrderStatus.PARTIALLY_DELIVERED,
        payment_status="overpaid", priority=OrderPriority.NORMAL,
    ),
    # 9. CLOSED — all done
    dict(
        id=ORDER_IDS["ord_9"], order_number="ORD-2026-000009",
        client_id=USERS["client_tc"], manager_id=USERS["manager1"], driver_id=USERS["driver1"],
        fuel_type=FuelType.DIESEL_SUMMER, volume_requested=Decimal("15000"), volume_delivered=Decimal("15000"),
        delivery_address="г. Москва, ул. Ленина, 10",
        payment_type=PaymentType.INVOICE, status=OrderStatus.CLOSED,
        payment_status="paid", priority=OrderPriority.NORMAL,
    ),
    # 10. REJECTED
    dict(
        id=ORDER_IDS["ord_10"], order_number="ORD-2026-000010",
        client_id=USERS["client_del"], manager_id=USERS["manager2"],
        fuel_type=FuelType.FUEL_OIL, volume_requested=Decimal("20000"),
        delivery_address="г. Москва, пр. Мира, 42",
        payment_type=PaymentType.ON_DELIVERY, status=OrderStatus.REJECTED,
        payment_status="unpaid", priority=OrderPriority.NORMAL,
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
    # ord_8: overpaid — client paid 100k, actual is 80k
    dict(id=PAYMENT_IDS["pay_4"], order_id=ORDER_IDS["ord_8"], client_id=USERS["client_pre"],
         kind=PaymentKind.PREPAYMENT, status=PaymentStatus.PAID, method=PaymentMethod.BANK_TRANSFER,
         amount=Decimal("100000"), paid_at=now - timedelta(days=5), created_by_id=USERS["manager2"],
         notes="Предоплата по плановому объёму"),
    # ord_9: closed, fully paid
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
        await session.execute(text("DELETE FROM order_year_counters WHERE year = 2026"))
        await session.commit()

        # Year counter
        session.add(OrderYearCounter(year=2026, last_seq=10))

        # Orders
        for o in ORDERS:
            o.setdefault("driver_id", None)
            o.setdefault("volume_delivered", None)
            o.setdefault("desired_date", None)
            o.setdefault("client_comment", None)
            o.setdefault("manager_comment", None)
            o.setdefault("rejection_reason", None)
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
    print(f"[seed:orders] Created {len(ORDERS)} orders, {len(PAYMENTS)} payments")


if __name__ == "__main__":
    asyncio.run(main())
