"""Заведение предопределённых пользователей (сотрудники + клиенты семьи Волковых).

Запуск внутри контейнера auth_service:
    docker compose exec -T auth_service python /app/scripts/seed_staff.py

Идемпотентно: пользователь определяется по нормализованному телефону (последние
10 цифр). Если уже есть — пропускаем. email не задаётся (вход по телефону);
пароли берутся как есть (в т.ч. короче 8 символов — это осознанное решение
заказчика, валидатор API здесь не применяется).

ВНИМАНИЕ: на APP_ENV=production скрипт не блокируется — это онбординг реальных
сотрудников. Запускать осознанно.
"""
import asyncio
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.client_profile import ClientProfile, ClientType
from app.core.security import hash_password
from app.core.phone import normalize_phone, normalized_phone_column


# (ФИО, телефон, пароль, роль, тип клиента | None)
USERS = [
    ("Волков Александр Сергеевич",      "8 921 947 65 77",     "VAS6577-s", UserRole.ADMIN,   None),
    ("Волкова Ирина Александровна",     "8 999 529 17 59",     "VIA1759-s", UserRole.ADMIN,   None),
    ("Волкова Екатерина Ивановна",      "8 921 903 22 77",     "VEI2277-s", UserRole.MANAGER, None),
    ("Волков Антон Александрович",      "8 921 849 33 37",     "VAA3337-s", UserRole.CLIENT,  ClientType.INDIVIDUAL),
    ("Волкова Надежда Васильевна",      "+7 (950) 041-09-30",  "VNV0930-s", UserRole.CLIENT,  ClientType.INDIVIDUAL),
    ("Бурнаев Сергей Викторович",       "+7 (911) 230-06-56",  "BSV0656",   UserRole.DRIVER,  None),
    ("Семенов Денис Анатольевич",       "+7 (952) 229-17-17",  "SDA1717",   UserRole.DRIVER,  None),
    ("Афонькин Александр Александрович", "+7 (931) 342-11-45",  "AAA1145",   UserRole.DRIVER,  None),
]


async def main() -> None:
    created, skipped = 0, 0
    async with AsyncSessionLocal() as db:
        for full_name, phone, password, role, client_type in USERS:
            norm = normalize_phone(phone)
            existing = await db.execute(
                select(User).where(normalized_phone_column(User.phone) == norm)
            )
            if existing.scalars().first():
                print(f"  = skip (exists): {full_name} / {phone}")
                skipped += 1
                continue

            user = User(
                email=None,
                phone=phone,
                hashed_password=hash_password(password),
                full_name=full_name,
                role=role,
            )
            db.add(user)
            await db.flush()
            if role == UserRole.CLIENT:
                db.add(ClientProfile(user_id=user.id, client_type=client_type or ClientType.INDIVIDUAL))
            print(f"  + created: {full_name} / {phone} [{role.value}]")
            created += 1

        await db.commit()
    print(f"[seed_staff] created={created} skipped={skipped} total={len(USERS)}")


if __name__ == "__main__":
    asyncio.run(main())
