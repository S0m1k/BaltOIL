from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from app.config import get_settings
from app.database import engine, AsyncSessionLocal, Base
from app.models.user import User, UserRole
from app.core.security import hash_password
from app.routers import auth, users, internal

limiter = Limiter(key_func=get_remote_address)

settings = get_settings()


async def _bootstrap_admin() -> None:
    """Create the default admin (and dev test users) on first startup."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.role == UserRole.ADMIN).limit(1))
        if result.scalar_one_or_none():
            return

        admin = User(
            email=settings.bootstrap_admin_email,
            hashed_password=hash_password(settings.bootstrap_admin_password),
            full_name="Администратор",
            role=UserRole.ADMIN,
        )
        db.add(admin)
        print(f"[bootstrap] Admin created: {settings.bootstrap_admin_email}")

        if settings.app_env == "development":
            from app.models.client_profile import ClientProfile, ClientType
            dev_users = [
                User(email="admin@baltoil.ru",   hashed_password=hash_password("Admin1234!"),  full_name="Иван Петров",    role=UserRole.ADMIN),
                User(email="manager@baltoil.ru", hashed_password=hash_password("Manager1!"),   full_name="Мария Сидорова", role=UserRole.MANAGER),
                User(email="driver@baltoil.ru",  hashed_password=hash_password("Driver11!"),   full_name="Алексей Кузнецов", role=UserRole.DRIVER),
                User(email="client@baltoil.ru",  hashed_password=hash_password("Client1!"),    full_name="ООО Тест",       role=UserRole.CLIENT),
            ]
            for u in dev_users:
                db.add(u)
            await db.flush()
            # Создаём профиль для тестового клиента
            client_user = next(u for u in dev_users if u.role == UserRole.CLIENT)
            db.add(ClientProfile(
                user_id=client_user.id,
                client_type=ClientType.COMPANY,
                company_name="ООО Тест",
                delivery_address="г. Калининград, ул. Тестовая, 1",
            ))
            print("[bootstrap] Dev test users created: admin/manager/driver/client @baltoil.ru")

        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: проверяем небезопасную CORS-конфигурацию
    if settings.app_env == "production" and "*" in settings.cors_origins:
        raise RuntimeError("CORS wildcard '*' запрещён в production. Задайте ALLOWED_ORIGINS явно.")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _bootstrap_admin()
    yield
    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="BaltOIL Auth Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(internal.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "auth"}
