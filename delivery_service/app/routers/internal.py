"""Внутренние эндпоинты delivery_service — только для межсервисных запросов."""
import hmac
import logging
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import get_settings
from app.schemas.inventory import FuelStockResponse
from app.services.inventory_service import compute_stock

log = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _verify_internal_secret(
    x_internal_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Проверяет X-Internal-Secret. 401 если заголовок отсутствует, 403 если не совпадает."""
    _settings = get_settings()
    if x_internal_secret is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Internal-Secret header is required",
        )
    if not hmac.compare_digest(
        x_internal_secret.encode(), _settings.internal_api_secret.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid internal secret",
        )


InternalDep = Annotated[None, Depends(_verify_internal_secret)]


@router.get(
    "/inventory/stock",
    response_model=list[FuelStockResponse],
    summary="Остатки топлива (для order_service)",
)
async def internal_get_stock(
    _: InternalDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Текущие остатки без проверки роли пользователя.

    Используется order_service для фильтрации «только топливо в наличии».
    """
    return await compute_stock(db)
