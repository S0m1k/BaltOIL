from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.models import call  # noqa: F401 — register models
from app.routers import calls as calls_router
from app.routers import webhook as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Создаём таблицы если их ещё нет (fallback к Alembic в entrypoint.sh)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="BaltOIL Call Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calls_router.router)
app.include_router(webhook_router.router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "call"}
