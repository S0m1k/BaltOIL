"""Тестовое окружение auth_service.

Требуется живой PostgreSQL (модели используют UUID/JSONB из postgresql-диалекта,
на sqlite они не работают). Адрес берётся из AUTH_TEST_DATABASE_URL, по умолчанию
поднятый локально контейнер:

    docker run -d --name baltoil-auth-test-pg \
        -e POSTGRES_PASSWORD=testpass -e POSTGRES_USER=testuser \
        -e POSTGRES_DB=authtest -p 55432:5432 postgres:16-alpine

    cd auth_service && python -m pytest

Схема накатывается ЧЕРЕЗ alembic (`alembic upgrade head`), а не через
Base.metadata.create_all — так тесты заодно проверяют, что миграции
согласованы с моделями.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SERVICE_ROOT = Path(__file__).resolve().parents[1]

TEST_DATABASE_URL = os.environ.get(
    "AUTH_TEST_DATABASE_URL",
    "postgresql+asyncpg://testuser:testpass@localhost:55432/authtest",
)

# Настройки читаются на import-time (app.config / app.database), поэтому env
# выставляем ДО любых импортов из app.*
os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("INTERNAL_API_SECRET", "test-internal-secret")
os.environ.setdefault("APP_ENV", "test")
# Redis в тестах не поднят; token_revocation/login_throttle работают fail-open.
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6399")

if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from app.database import AsyncSessionLocal, engine  # noqa: E402
from app import models  # noqa: E402,F401  — регистрация всех моделей в metadata

TABLES_TO_CLEAN = (
    "audit_logs",
    "refresh_tokens",
    "organization_members",
    "organizations",
    "client_profiles",
    "users",
)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    """Накатывает alembic upgrade head на тестовую БД."""
    env = {**os.environ, "DATABASE_URL": TEST_DATABASE_URL}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(SERVICE_ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head failed:\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    yield


@pytest.fixture
async def db(migrated_database):
    """Чистая сессия на тест; таблицы очищаются перед каждым тестом.

    Движок диспозится после каждого теста: у каждого теста свой event loop,
    а пул asyncpg-соединений к чужому loop не привязывается.
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("TRUNCATE " + ", ".join(TABLES_TO_CLEAN) + " RESTART IDENTITY CASCADE")
        )

    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.rollback()
        await session.close()
        await engine.dispose()
