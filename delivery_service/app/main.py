import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.routers import vehicles, trips, reports, inventory, downloads
from app.routers import internal as internal_router
from app.routers import zones as zones_router
from app.routers import tanks as tanks_router
from app.routers.downloads import _purge_loop

settings = get_settings()

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
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    purge_task = asyncio.create_task(_purge_loop())
    yield
    purge_task.cancel()
    await engine.dispose()


app = FastAPI(
    title="BaltOIL Delivery Service",
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

app.include_router(vehicles.router,   prefix="/api/v1")
app.include_router(trips.router,      prefix="/api/v1")
app.include_router(reports.router,    prefix="/api/v1")
app.include_router(tanks_router.router, prefix="/api/v1")  # до inventory: /inventory/tanks специфичнее
app.include_router(inventory.router,  prefix="/api/v1")
app.include_router(downloads.router,     prefix="/api/v1")
app.include_router(internal_router.router, prefix="/api/v1")
app.include_router(zones_router.router,   prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "delivery"}
