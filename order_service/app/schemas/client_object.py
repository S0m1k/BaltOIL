import uuid
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field, field_validator


class ClientObjectCreateRequest(BaseModel):
    delivery_address: str = Field(..., min_length=1)
    name: str | None = Field(None, max_length=120)
    delivery_lat: float | None = Field(None, ge=-90, le=90)
    delivery_lon: float | None = Field(None, ge=-180, le=180)
    # Только для staff: создать объект для конкретного клиента
    client_id: uuid.UUID | None = None

    @field_validator("delivery_address", mode="before")
    @classmethod
    def strip_address(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("delivery_address не может быть пустым")
        return v


class ClientObjectResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    client_id: uuid.UUID
    name: str | None
    delivery_address: str
    delivery_lat: Decimal | None
    delivery_lon: Decimal | None
    created_at: datetime
