import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.routers.devices import router as devices_router
from app.routers.internal import router as internal_router
from app.routers.notifications import router as notif_router
from app.routers.redis_subscriber import redis_subscriber_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_DEFAULT_JWT_SECRET = "change-me-to-a-very-long-random-secret"
_DEFAULT_INTERNAL_SECRET = "baltoil-internal-secret-2026"


def _assert_prod_secrets_safe() -> None:
    if settings.app_env != "production":
        return
    issues = []
    if settings.jwt_secret_key == _DEFAULT_JWT_SECRET or len(settings.jwt_secret_key) < 32:
        issues.append("JWT_SECRET_KEY")
    if settings.internal_api_secret == _DEFAULT_INTERNAL_SECRET:
        issues.append("INTERNAL_API_SECRET")
    if any("localhost" in o for o in settings.cors_origins) or "*" in settings.cors_origins:
        issues.append("ALLOWED_ORIGINS")
    if issues:
        raise RuntimeError("Небезопасные дефолты в production: " + ", ".join(issues))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _assert_prod_secrets_safe()
    # Create tables first — иначе ALTER TYPE ниже падает на пустой БД, где
    # notificationtype ещё не создан (create_all лепит и тип, и таблицы).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Затем добиваем новые enum-value, которые могли появиться в коде позже
    # первичного create_all (он не модифицирует существующий тип).
    from sqlalchemy import text as _sql_text
    _new_enum_values = ["report_ready", "call_initiated", "call_ended", "call_missed", "chat_new"]
    async with engine.begin() as conn:
        for _val in _new_enum_values:
            await conn.execute(
                _sql_text(
                    f"DO $$ BEGIN "
                    f"  IF NOT EXISTS (SELECT 1 FROM pg_enum WHERE enumlabel = '{_val}' "
                    f"    AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'notificationtype')) "
                    f"  THEN ALTER TYPE notificationtype ADD VALUE '{_val}'; END IF; "
                    f"END $$;"
                )
            )
    logger.info("Notification DB tables ready")

    # Start Redis subscriber
    task = asyncio.create_task(redis_subscriber_task())
    logger.info("Redis subscriber task started")

    yield

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await engine.dispose()


app = FastAPI(title="BaltOIL Notification Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(internal_router)
app.include_router(notif_router, prefix="/api/v1/notifications", tags=["notifications"])
app.include_router(devices_router, prefix="/api/v1/devices", tags=["devices"])


@app.get("/health")
async def health():
    return {"status": "ok"}
