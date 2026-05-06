import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.trip import TripStatus


class TripCreateRequest(BaseModel):
    order_id: uuid.UUID
    vehicle_id: uuid.UUID
    volume_planned: float = Field(..., gt=0)
    delivery_address: str
    odometer_start: float | None = None
    driver_notes: str | None = None
    # Required when created by manager/admin; ignored when driver creates for themselves
    driver_id: uuid.UUID | None = None


class TripStartRequest(BaseModel):
    odometer_start: float | None = None
    driver_notes: str | None = None


class TripCompleteRequest(BaseModel):
    volume_actual: float = Field(..., gt=0)
    odometer_end: float | None = None
    driver_notes: str | None = None


class TripResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID
    status: TripStatus
    volume_planned: float
    volume_actual: float | None
    odometer_start: float | None
    odometer_end: float | None
    departed_at: datetime | None
    arrived_at: datetime | None
    delivery_address: str
    driver_notes: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
