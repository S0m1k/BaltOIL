import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import engine, Base
from app.routers import vehicles, trips, reports, inventory, downloads
from app.routers.downloads import _purge_loop

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.include_router(inventory.router,  prefix="/api/v1")
app.include_router(downloads.router,  prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "delivery"}
