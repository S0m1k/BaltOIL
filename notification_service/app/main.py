import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.routers.notifications import router as notif_router
from app.routers.redis_subscriber import redis_subscriber_task

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
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

app.include_router(notif_router, prefix="/api/v1/notifications", tags=["notifications"])


@app.get("/health")
async def health():
    return {"status": "ok"}
