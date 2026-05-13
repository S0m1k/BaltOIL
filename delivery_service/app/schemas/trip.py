import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from app.models.trip import TripStatus


class TripAutoStartRequest(BaseModel):
    """Тело для авто-создания рейса при переходе заявки в in_transit.
    Вызывается из order_service — передаёт данные заявки целиком.
    """
    order_id: uuid.UUID
    driver_id: uuid.UUID
    volume_planned: float = Field(..., gt=0, le=1_000_000)
    delivery_address: str = Field(default="", max_length=500)
    # Контекст учёта топлива
    inv_fuel_type: str | None = Field(None, max_length=50)
    inv_order_number: str | None = Field(None, max_length=30)
    inv_client_id: uuid.UUID | None = None
    inv_client_name: str | None = Field(None, max_length=255)
    inv_driver_name: str | None = Field(None, max_length=255)


class TripCreateRequest(BaseModel):
    order_id: uuid.UUID
    vehicle_id: uuid.UUID | None = None
    volume_planned: float = Field(..., gt=0, le=1_000_000)
    delivery_address: str = Field(default="", max_length=500)
    driver_notes: str | None = Field(None, max_length=1000)
    driver_id: uuid.UUID | None = None
    inv_fuel_type: str | None = Field(None, max_length=50)
    inv_order_number: str | None = Field(None, max_length=30)
    inv_client_id: uuid.UUID | None = None
    inv_client_name: str | None = Field(None, max_length=255)
    inv_driver_name: str | None = Field(None, max_length=255)


class TripStartRequest(BaseModel):
    driver_notes: str | None = Field(None, max_length=1000)


class TripCompleteRequest(BaseModel):
    volume_actual: float = Field(..., gt=0, le=1_000_000)
    driver_notes: str | None = Field(None, max_length=1000)


class TripResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    driver_id: uuid.UUID
    vehicle_id: uuid.UUID | None
    status: TripStatus
    volume_planned: float
    volume_actual: float | None
    departed_at: datetime | None
    arrived_at: datetime | None
    delivery_address: str | None
    driver_notes: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    inv_fuel_type: str | None = None
    inv_order_number: str | None = None
    inv_client_id: uuid.UUID | None = None
    inv_client_name: str | None = None
    inv_driver_name: str | None = None

    model_config = {"from_attributes": True}
