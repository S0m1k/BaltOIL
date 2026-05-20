from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.models import conversation, message  # noqa: F401 — register models
from app.routers import conversations, websocket as ws_router, internal as internal_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=50,
    )

    # Ensure the three staff_group conversations exist on every startup (idempotent).
    # These are pre-configured groups that must always exist: general, drivers, managers.
    from app.database import AsyncSessionLocal
    from app.services.conversation_service import ensure_staff_groups
    async with AsyncSessionLocal() as db:
        await ensure_staff_groups(db)

    try:
        yield
    finally:
        await app.state.redis.aclose()


app = FastAPI(title="BaltOIL Chat Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(ws_router.router)
app.include_router(internal_router.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "chat"}
