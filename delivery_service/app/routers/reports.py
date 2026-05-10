import uuid
from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from app.database import get_db
from app.config import get_settings
from app.core.dependencies import CurrentUser
from app.schemas.report import DriverReportResponse
from app.services import report_service
from app.services.excel_service import driver_report_xlsx
from app.routers.downloads import store_file

router = APIRouter(prefix="/reports", tags=["reports"])
_settings = get_settings()


@router.get("/driver", response_model=DriverReportResponse)
async def get_driver_report(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    driver_id: uuid.UUID = Query(..., description="UUID водителя"),
    date_from: datetime = Query(..., description="Начало периода (ISO 8601)"),
    date_to: datetime = Query(..., description="Конец периода (ISO 8601)"),
):
    """
    Отчёт по рейсам водителя за период.
    Водитель может получить только свой. Менеджер/Админ — любого.
    """
    return await report_service.driver_report(
        db, current_user,
        driver_id=driver_id,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/driver/xlsx", status_code=202)
async def request_driver_report_xlsx(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    driver_id: uuid.UUID = Query(..., description="UUID водителя"),
    date_from: datetime = Query(..., description="Начало периода (ISO 8601)"),
    date_to: datetime = Query(..., description="Конец периода (ISO 8601)"),
):
    """Сформировать XLSX-отчёт по рейсам и отправить уведомление со ссылкой."""
    rpt = await report_service.driver_report(
        db, current_user,
        driver_id=driver_id,
        date_from=date_from,
        date_to=date_to,
    )

    rpt_dict = rpt.model_dump(mode="json")
    xlsx_bytes = driver_report_xlsx(rpt_dict)

    date_label = date_from.strftime("%Y%m%d") + "-" + date_to.strftime("%Y%m%d")
    filename   = f"driver_report_{date_label}.xlsx"
    file_id    = store_file(filename, xlsx_bytes, str(current_user.id))

    download_url = f"{_settings.public_delivery_url}/api/v1/reports/download/{file_id}"

    await _notify(
        user_id=current_user.id,
        title="Отчёт по рейсам готов",
        body=(
            f"Период: {date_from.strftime('%d.%m.%Y')} — {date_to.strftime('%d.%m.%Y')}. "
            f"Рейсов: {rpt_dict['total_trips']}, завершено: {rpt_dict['completed_trips']}.\n"
            f"[Скачать XLSX]({download_url})"
        ),
        entity_type="xlsx_download",
        entity_id=file_id,
    )

    return {"status": "queued", "message": "Отчёт формируется, вы получите уведомление"}


async def _notify(
    *,
    user_id: uuid.UUID,
    title: str,
    body: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> None:
    """Publish a notification via the internal endpoint (fire-and-forget)."""
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
        pass  # не блокируем основной запрос
