import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trip import Trip, TripStatus
from app.core.dependencies import TokenUser, ROLE_DRIVER, ROLE_ADMIN, ROLE_MANAGER
from app.core.exceptions import ForbiddenError
from app.schemas.report import DriverReportResponse
from app.services.trip_service import list_trips


async def driver_report(
    db: AsyncSession,
    actor: TokenUser,
    *,
    driver_id: uuid.UUID,
    date_from: datetime,
    date_to: datetime,
) -> DriverReportResponse:
    # Водитель может получить только свой отчёт
    if actor.role == ROLE_DRIVER and actor.id != driver_id:
        raise ForbiddenError("Можно получить только собственный отчёт")
    if actor.role not in (ROLE_DRIVER, ROLE_MANAGER, ROLE_ADMIN):
        raise ForbiddenError()

    trips = await list_trips(
        db, actor,
        driver_id=driver_id,
        date_from=date_from,
        date_to=date_to,
        limit=1000,
    )

    completed = [t for t in trips if t.status == TripStatus.COMPLETED]
    cancelled = [t for t in trips if t.status == TripStatus.CANCELLED]

    total_volume_planned = sum(float(t.volume_planned) for t in trips)
    total_volume_actual  = sum(float(t.volume_actual) for t in completed if t.volume_actual)

    distances = []
    for t in completed:
        if t.odometer_start is not None and t.odometer_end is not None:
            distances.append(float(t.odometer_end) - float(t.odometer_start))
    total_distance = sum(distances) if distances else None

    return DriverReportResponse(
        driver_id=driver_id,
        period_from=date_from,
        period_to=date_to,
        total_trips=len(trips),
        completed_trips=len(completed),
        cancelled_trips=len(cancelled),
        total_volume_planned=total_volume_planned,
        total_volume_actual=total_volume_actual,
        total_distance_km=total_distance,
        trips=trips,
    )
