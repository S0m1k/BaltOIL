import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.routers.internal import router as internal_router
from app.routers.notifications import router as notif_router
from app.routers.redis_subscriber import redis_subscriber_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Add new enum values if not present (safe to run multiple times)
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
    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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


@app.get("/health")
async def health():
    return {"status": "ok"}
