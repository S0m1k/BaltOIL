import uuid
from datetime import datetime
from pydantic import BaseModel
from .trip import TripResponse


class DriverReportResponse(BaseModel):
    driver_id: uuid.UUID
    period_from: datetime
    period_to: datetime

    total_trips: int
    completed_trips: int
    cancelled_trips: int

    total_volume_planned: float
    total_volume_actual: float

    total_distance_km: float | None  # сумма (odometer_end - odometer_start)

    trips: list[TripResponse]
