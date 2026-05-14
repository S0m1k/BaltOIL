from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.models import order, order_status_log, order_counter, payment, legal_entity, document, tariff  # noqa: F401 — register all models
from app.routers import orders, fuel_types, payments, legal_entity as legal_entity_router, documents, finance, tariffs

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


app = FastAPI(
    title="BaltOIL Order Service",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router, prefix="/api/v1")
app.include_router(fuel_types.router, prefix="/api/v1")
app.include_router(payments.router, prefix="/api/v1")
app.include_router(legal_entity_router.router, prefix="/api/v1")
app.include_router(documents.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")
app.include_router(tariffs.router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "order"}
