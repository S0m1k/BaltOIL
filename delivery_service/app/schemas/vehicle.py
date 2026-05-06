import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class VehicleCreateRequest(BaseModel):
    plate_number: str
    model: str
    capacity_liters: float = Field(..., gt=0)
    assigned_driver_id: uuid.UUID | None = None
    notes: str | None = None


class VehicleUpdateRequest(BaseModel):
    plate_number: str | None = None
    model: str | None = None
    capacity_liters: float | None = Field(None, gt=0)
    assigned_driver_id: uuid.UUID | None = None
    notes: str | None = None
    is_active: bool | None = None


class VehicleResponse(BaseModel):
    id: uuid.UUID
    plate_number: str
    model: str
    capacity_liters: float
    assigned_driver_id: uuid.UUID | None
    notes: str | None
    is_active: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
