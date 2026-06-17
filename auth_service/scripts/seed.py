"""
Dev seed for auth_service: creates test users and client profiles.
FORBIDDEN on production (APP_ENV=production).
Run via: docker compose exec auth_service python /app/scripts/seed.py
"""
import asyncio
import os
import uuid
import sys

# Safety guard — must be first executable line
if os.environ.get("APP_ENV") == "production":
    print("ERROR: seed.py is FORBIDDEN on production", file=sys.stderr)
    sys.exit(1)

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Add /app to path so we can import app modules
sys.path.insert(0, "/app")

from app.config import get_settings
from app.core.security import hash_password
from app.models import User, UserRole, ClientProfile, ClientType

settings = get_settings()

# Fixed UUIDs for determinism across seed runs — reuse these in other service seeds
USERS = {
    "admin":        uuid.UUID("00000000-0000-0000-0000-000000000001"),
    "manager1":     uuid.UUID("00000000-0000-0000-0000-000000000002"),
    "manager2":     uuid.UUID("00000000-0000-0000-0000-000000000003"),
    "driver1":      uuid.UUID("00000000-0000-0000-0000-000000000004"),
    "driver2":      uuid.UUID("00000000-0000-0000-0000-000000000005"),
    "client_pre":   uuid.UUID("00000000-0000-0000-0000-000000000011"),  # prepaid
    "client_del":   uuid.UUID("00000000-0000-0000-0000-000000000012"),  # on_delivery
    "client_tc":    uuid.UUID("00000000-0000-0000-0000-000000000013"),  # trade_credit
    "client_post":  uuid.UUID("00000000-0000-0000-0000-000000000014"),  # postpaid
    "client_mix":   uuid.UUID("00000000-0000-0000-0000-000000000015"),  # mixed / company
    # Захардкоженные реальные сотрудники (паспортные данные заполняет админ в UI)
    "volkov_a":     uuid.UUID("00000000-0000-0000-0000-000000000021"),  # Волков Александр Сергеевич
    "volkova_i":    uuid.UUID("00000000-0000-0000-0000-000000000022"),  # Волкова Ирина Александровна
    "volkova_e":    uuid.UUID("00000000-0000-0000-0000-000000000023"),  # Волкова Екатерина Ивановна
    "volkov_an":    uuid.UUID("00000000-0000-0000-0000-000000000024"),  # Волков Антон Александрович
    "volkova_n":    uuid.UUID("00000000-0000-0000-0000-000000000025"),  # Волкова Надежда Васильевна
}

HASHED_PASSWORD = hash_password("password123")

USER_RECORDS = [
    dict(id=USERS["admin"],       email="admin@baltoil.test",      role=UserRole.ADMIN,    full_name="Главный Администратор"),
    dict(id=USERS["manager1"],    email="manager1@baltoil.test",   role=UserRole.MANAGER,  full_name="Менеджер Первый"),
    dict(id=USERS["manager2"],    email="manager2@baltoil.test",   role=UserRole.MANAGER,  full_name="Менеджер Второй"),
    dict(id=USERS["driver1"],     email="driver1@baltoil.test",    role=UserRole.DRIVER,   full_name="Водитель Первый"),
    dict(id=USERS["driver2"],     email="driver2@baltoil.test",    role=UserRole.DRIVER,   full_name="Водитель Второй"),
    dict(id=USERS["client_pre"],  email="prepaid@baltoil.test",    role=UserRole.CLIENT,   full_name="Клиент Предоплата"),
    dict(id=USERS["client_del"],  email="ondelivery@baltoil.test", role=UserRole.CLIENT,   full_name="Клиент По Факту"),
    dict(id=USERS["client_tc"],   email="tradecredit@baltoil.test",role=UserRole.CLIENT,   full_name="Клиент Товарный Кредит"),
    dict(id=USERS["client_post"], email="postpaid@baltoil.test",   role=UserRole.CLIENT,   full_name="Клиент Постоплата"),
    dict(id=USERS["client_mix"],  email="company@baltoil.test",    role=UserRole.CLIENT,   full_name="ООО Ромашка"),
    # Захардкоженные сотрудники семьи Волковых. Паспортные данные оставляем
    # пустыми — их вносит/меняет админ во вкладке «Пользователи».
    dict(id=USERS["volkov_a"],    email="volkov.a@baltoil.test",   role=UserRole.ADMIN,    full_name="Волков Александр Сергеевич"),
    dict(id=USERS["volkova_i"],   email="volkova.i@baltoil.test",  role=UserRole.ADMIN,    full_name="Волкова Ирина Александровна"),
    dict(id=USERS["volkova_e"],   email="volkova.e@baltoil.test",  role=UserRole.MANAGER,  full_name="Волкова Екатерина Ивановна"),
    dict(id=USERS["volkov_an"],   email="volkov.an@baltoil.test",  role=UserRole.CLIENT,   full_name="Волков Антон Александрович"),
    dict(id=USERS["volkova_n"],   email="volkova.n@baltoil.test",  role=UserRole.CLIENT,   full_name="Волкова Надежда Васильевна"),
]

CLIENT_PROFILES = [
    dict(id=uuid.uuid4(), user_id=USERS["client_pre"],  client_type=ClientType.INDIVIDUAL, delivery_address="г. Москва, ул. Тестовая, 1"),
    dict(id=uuid.uuid4(), user_id=USERS["client_del"],  client_type=ClientType.INDIVIDUAL, delivery_address="г. Москва, пр. Мира, 42"),
    dict(id=uuid.uuid4(), user_id=USERS["client_tc"],   client_type=ClientType.COMPANY,    delivery_address="г. Москва, ул. Ленина, 10",
         company_name="ООО Топливо Трейд", inn="7701234567", kpp="770101001", credit_allowed=True),
    dict(id=uuid.uuid4(), user_id=USERS["client_post"], client_type=ClientType.INDIVIDUAL, delivery_address="г. Москва, ул. Садовая, 7"),
    dict(id=uuid.uuid4(), user_id=USERS["client_mix"],  client_type=ClientType.COMPANY,    delivery_address="г. Москва, Лесная ул., 25",
         company_name="ООО Ромашка", inn="7709876543", kpp="770901001"),
]


async def main():
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as session:
        # Wipe existing seed data idempotently. Чистим не только по фиксированным
        # UUID, но и по email/ФИО — захардкоженные сотрудники могли уже
        # существовать в БД под другими UUID (иначе INSERT упадёт на unique email
        # или создаст дубли).
        known_ids = list(USERS.values())
        emails = [r["email"] for r in USER_RECORDS if r.get("email")]
        names = [r["full_name"] for r in USER_RECORDS if r.get("full_name")]
        rows = (await session.execute(
            text("SELECT id FROM users WHERE id = ANY(:ids) OR email = ANY(:emails) OR full_name = ANY(:names)"),
            {"ids": known_ids, "emails": emails, "names": names},
        )).all()
        wipe_ids = list({*known_ids, *(row[0] for row in rows)})
        await session.execute(
            text("DELETE FROM client_profiles WHERE user_id = ANY(:ids)"),
            {"ids": wipe_ids},
        )
        await session.execute(
            text("DELETE FROM refresh_tokens WHERE user_id = ANY(:ids)"),
            {"ids": wipe_ids},
        )
        await session.execute(
            text("DELETE FROM users WHERE id = ANY(:ids)"),
            {"ids": wipe_ids},
        )
        await session.commit()

        # Create users
        for u in USER_RECORDS:
            session.add(User(hashed_password=HASHED_PASSWORD, is_active=True, is_archived=False, **u))
        await session.commit()

        # Create client profiles
        for cp in CLIENT_PROFILES:
            cp.setdefault("credit_allowed", False)
            cp.setdefault("fuel_coefficient", 1.0)
            cp.setdefault("delivery_coefficient", 1.0)
            session.add(ClientProfile(**cp))
        await session.commit()

    await engine.dispose()
    print(f"[seed:auth] Created {len(USER_RECORDS)} users, {len(CLIENT_PROFILES)} client profiles")
    print("[seed:auth] Logins: admin@baltoil.test / password123  (and manager1@, driver1@, prepaid@, etc.)")


if __name__ == "__main__":
    asyncio.run(main())
