import asyncio
import uuid
from datetime import datetime
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.database import get_db
from app.config import get_settings
from app.core.dependencies import TokenUser, require_roles, ROLE_MANAGER, ROLE_ADMIN, CurrentUser
from app.schemas.inventory import (
    FuelStockResponse, ArrivalRequest,
    TransactionResponse, InventoryReport,
)
from app.services import inventory_service
from app.services.excel_service import inventory_report_xlsx
from app.routers.downloads import store_file

_settings = get_settings()

router = APIRouter(prefix="/inventory", tags=["inventory"])

# Dependency: только менеджер или админ
ManagerOrAdmin = Annotated[TokenUser, Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN))]


@router.get("/stock", response_model=list[FuelStockResponse], summary="Текущие остатки топлива")
async def get_stock(
    current_user: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Текущий остаток по каждому виду топлива на складе."""
    return await inventory_service.get_stock(db, current_user)


@router.post("/arrivals", response_model=TransactionResponse, status_code=201,
             summary="Записать приход топлива")
async def record_arrival(
    data: ArrivalRequest,
    current_user: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Менеджер / администратор фиксирует поступление топлива на склад."""
    return await inventory_service.record_arrival(db, data, current_user)


@router.get("/transactions", response_model=list[TransactionResponse],
            summary="Список операций прихода/расхода")
async def list_transactions(
    current_user: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
    fuel_type: str | None = Query(None, description="diesel_summer / diesel_winter / petrol_92 / petrol_95 / fuel_oil"),
    type: str | None = Query(None, description="arrival | departure", pattern="^(arrival|departure)$"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    return await inventory_service.list_transactions(
        db, current_user,
        fuel_type=fuel_type,
        tx_type=type,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
    )


@router.post("/reconcile", response_model=list[FuelStockResponse],
             summary="Пересчитать остатки из транзакций (только admin)")
async def reconcile_stock(
    current_user: Annotated[TokenUser, Depends(require_roles(ROLE_ADMIN))],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Пересчитывает fuel_stock из суммы всех транзакций. Исправляет рассинхрон."""
    return await inventory_service.reconcile_stock(db, current_user)


@router.get("/report", response_model=InventoryReport, summary="Сводный отчёт за период")
async def generate_report(
    current_user: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: datetime = Query(..., description="Начало периода (ISO 8601)"),
    date_to: datetime = Query(..., description="Конец периода (ISO 8601)"),
    fuel_type: str | None = Query(None, description="Фильтр по виду топлива (пусто = все)"),
):
    """
    Сводный отчёт: входящий остаток, приход, расход, исходящий остаток +
    детализация каждой операции (рейс, клиент, водитель).
    """
    return await inventory_service.generate_report(
        db, current_user,
        date_from=date_from,
        date_to=date_to,
        fuel_type=fuel_type,
    )


@router.post("/report/xlsx", status_code=202, summary="Запросить складской отчёт в формате XLSX")
async def request_inventory_report_xlsx(
    current_user: ManagerOrAdmin,
    db: Annotated[AsyncSession, Depends(get_db)],
    date_from: datetime = Query(..., description="Начало периода (ISO 8601)"),
    date_to: datetime = Query(..., description="Конец периода (ISO 8601)"),
    fuel_type: str | None = Query(
        None,
        description="Фильтр по виду топлива (пусто = все)",
        pattern=r"^(diesel_summer|diesel_winter|petrol_92|petrol_95|fuel_oil)$",
    ),
):
    """Сформировать XLSX складского отчёта и отправить уведомление со ссылкой."""
    rpt = await inventory_service.generate_report(
        db, current_user,
        date_from=date_from,
        date_to=date_to,
        fuel_type=fuel_type,
    )

    rpt_dict = rpt.model_dump(mode="json")
    xlsx_bytes = await asyncio.to_thread(inventory_report_xlsx, rpt_dict)

    date_label = date_from.strftime("%Y%m%d") + "-" + date_to.strftime("%Y%m%d")
    fuel_label = f"_{fuel_type}" if fuel_type else ""
    filename   = f"inventory_report{fuel_label}_{date_label}.xlsx"
    file_id    = store_file(filename, xlsx_bytes, str(current_user.id))

    download_url = f"{_settings.public_delivery_url}/api/v1/reports/download/{file_id}"

    summary_parts = [
        f"{s['fuel_label']}: {s['total_departures']} л расход"
        for s in rpt_dict.get("summary", [])
        if s["total_arrivals"] > 0 or s["total_departures"] > 0
    ]
    body = (
        f"Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}. "
        + (", ".join(summary_parts[:3]) or "Нет операций")
        + f".\n[Скачать XLSX]({download_url})"
    )

    await _notify_inv(
        user_id=current_user.id,
        title="Складской отчёт готов",
        body=body,
        entity_type="xlsx_download",
        entity_id=file_id,
    )

    return {"status": "queued", "message": "Отчёт формируется, вы получите уведомление"}


async def _notify_inv(
    *,
    user_id: uuid.UUID,
    title: str,
    body: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    payload = {
        "user_ids": [str(user_id)],
        "type": "report_ready",
        "title": title,
        "body": body,
        "entity_type": entity_type,
        "entity_id": entity_id,
    }
    notif_url = _settings.notification_service_url
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"{notif_url}/api/v1/notifications/internal/publish",
                json=payload,
                headers={"X-Internal-Secret": _settings.internal_api_secret},
            )
    except Exception:
        pass
