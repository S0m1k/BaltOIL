import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class VehicleCreateRequest(BaseModel):
    plate_number: str = Field(..., max_length=20)
    model: str = Field(..., max_length=100)
    capacity_liters: float = Field(..., gt=0, le=200_000)
    assigned_driver_id: uuid.UUID | None = None
    notes: str | None = Field(None, max_length=500)


class VehicleUpdateRequest(BaseModel):
    plate_number: str | None = Field(None, max_length=20)
    model: str | None = Field(None, max_length=100)
    capacity_liters: float | None = Field(None, gt=0, le=200_000)
    assigned_driver_id: uuid.UUID | None = None
    notes: str | None = Field(None, max_length=500)
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
