"""Заведение предопределённых пользователей (онбординг сотрудников/клиентов).

Учётные данные НЕ хранятся в репозитории. Список пользователей читается из
JSON-файла (по умолчанию /app/scripts/staff_users.json — он в .gitignore).

Формат файла — массив объектов:
  [
    {"full_name": "...", "phone": "8 999 ...", "password": "...",
     "role": "admin|manager|driver|client", "client_type": "individual|company|null"},
    ...
  ]

Запуск внутри контейнера auth_service:
    docker compose exec -T auth_service python /app/scripts/seed_staff.py
    # или с другим путём к файлу:
    docker compose exec -T -e STAFF_USERS_FILE=/app/scripts/my.json auth_service python /app/scripts/seed_staff.py

Идемпотентно: пользователь определяется по нормализованному телефону (последние
10 цифр). Если уже есть — пропускаем. email не задаётся (вход по телефону);
пароли берутся как есть (в т.ч. короче 8 символов — осознанное решение
заказчика, валидатор API здесь не применяется).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/app")

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.models.client_profile import ClientProfile, ClientType
from app.core.security import hash_password
from app.core.phone import normalize_phone, normalized_phone_column

STAFF_USERS_FILE = os.environ.get("STAFF_USERS_FILE", "/app/scripts/staff_users.json")


def _load_users() -> list[dict]:
    if not os.path.exists(STAFF_USERS_FILE):
        sys.exit(
            f"FATAL: файл {STAFF_USERS_FILE} не найден.\n"
            "Создайте его рядом со скриптом (он в .gitignore) — формат см. в docstring."
        )
    with open(STAFF_USERS_FILE, encoding="utf-8") as f:
        return json.load(f)


async def main() -> None:
    users = _load_users()
    created, skipped = 0, 0
    async with AsyncSessionLocal() as db:
        for u in users:
            full_name = u["full_name"]
            phone = u["phone"]
            password = u["password"]
            role = UserRole(u["role"])
            ct = u.get("client_type")
            client_type = ClientType(ct) if ct else None

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
    print(f"[seed_staff] created={created} skipped={skipped} total={len(users)}")


if __name__ == "__main__":
    asyncio.run(main())
