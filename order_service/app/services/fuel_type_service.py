"""Сервис каталога топлива: CRUD + валидация + межсервисный запрос остатков."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import httpx

from app.config import get_settings
from app.models.fuel_type_catalog import FuelTypeCatalog
from app.schemas.fuel_type import FuelTypeCreate, FuelTypeUpdate
from app.core.exceptions import ValidationError, NotFoundError

log = logging.getLogger(__name__)


async def list_active(db: AsyncSession) -> list[FuelTypeCatalog]:
    """Все активные записи, отсортированные по sort_order, code."""
    result = await db.execute(
        select(FuelTypeCatalog)
        .where(FuelTypeCatalog.is_active == True)  # noqa: E712
        .order_by(FuelTypeCatalog.sort_order, FuelTypeCatalog.code)
    )
    return list(result.scalars().all())


async def list_all(db: AsyncSession) -> list[FuelTypeCatalog]:
    """Все записи (включая неактивные) — для внутреннего API."""
    result = await db.execute(
        select(FuelTypeCatalog)
        .order_by(FuelTypeCatalog.sort_order, FuelTypeCatalog.code)
    )
    return list(result.scalars().all())


async def get_by_code(db: AsyncSession, code: str) -> FuelTypeCatalog | None:
    result = await db.execute(
        select(FuelTypeCatalog).where(FuelTypeCatalog.code == code)
    )
    return result.scalar_one_or_none()


async def create_fuel_type(db: AsyncSession, data: FuelTypeCreate) -> FuelTypeCatalog:
    existing = await get_by_code(db, data.code)
    if existing is not None:
        raise ValidationError(f"Вид топлива с кодом «{data.code}» уже существует")
    entry = FuelTypeCatalog(
        code=data.code,
        label=data.label,
        is_winter=data.is_winter,
        sort_order=data.sort_order,
        is_active=True,
    )
    db.add(entry)
    await db.flush()
    return entry


async def update_fuel_type(
    db: AsyncSession, code: str, data: FuelTypeUpdate
) -> FuelTypeCatalog:
    entry = await get_by_code(db, code)
    if entry is None:
        raise NotFoundError(f"Вид топлива «{code}» не найден")
    if data.label is not None:
        entry.label = data.label
    if data.is_winter is not None:
        entry.is_winter = data.is_winter
    if data.sort_order is not None:
        entry.sort_order = data.sort_order
    if data.is_active is not None:
        entry.is_active = data.is_active
    await db.flush()
    return entry


async def soft_delete(db: AsyncSession, code: str) -> FuelTypeCatalog:
    """Деактивация — мягкое удаление, исторические заявки сохраняют код."""
    entry = await get_by_code(db, code)
    if entry is None:
        raise NotFoundError(f"Вид топлива «{code}» не найден")
    entry.is_active = False
    await db.flush()
    return entry


async def validate_active(db: AsyncSession, code: str) -> None:
    """Проверить что код топлива существует и активен.

    Используется при создании заявки.
    Поднимает ValidationError с русским сообщением.
    """
    entry = await get_by_code(db, code)
    if entry is None:
        raise ValidationError(f"Вид топлива «{code}» не найден в каталоге")
    if not entry.is_active:
        raise ValidationError(f"Вид топлива «{entry.label}» деактивирован и недоступен для заказа")


async def fetch_in_stock_codes() -> set[str] | None:
    """Получить коды топлива с остатком > 0 из delivery_service.

    Возвращает None при сетевой ошибке (вызывающий код должен fail-open).
    """
    _settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{_settings.delivery_service_url}/api/v1/internal/inventory/stock",
                headers={"X-Internal-Secret": _settings.internal_api_secret},
            )
        if r.status_code != 200:
            log.warning(
                "fetch_in_stock_codes: delivery_service returned %s", r.status_code
            )
            return None
        data = r.json()
        return {item["fuel_type"] for item in data if item.get("current_volume", 0) > 0}
    except Exception as exc:
        log.warning("fetch_in_stock_codes: failed to reach delivery_service: %s", exc)
        return None
