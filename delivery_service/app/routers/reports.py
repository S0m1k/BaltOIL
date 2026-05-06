import uuid
from typing import Annotated
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser
from app.schemas.report import DriverReportResponse
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


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
