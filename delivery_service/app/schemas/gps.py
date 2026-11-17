"""Схемы GPS-мониторинга."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class GpsDeviceResponse(BaseModel):
    id: uuid.UUID
    device_number: str
    label: str | None = None
    sim_phone: str | None = None
    notes: str | None = None
    is_active: bool
    # Трекер завёлся сам, прислав точку, и ещё не подтверждён админом.
    auto_registered: bool
    has_token: bool
    vehicle_id: uuid.UUID | None = None
    vehicle_plate: str | None = None
    vehicle_model: str | None = None
    # online / stale / offline / never — считается по last_seen_at
    status: str
    last_seen_at: datetime | None = None
    last_fix_at: datetime | None = None
    last_lat: Decimal | None = None
    last_lon: Decimal | None = None
    last_sats: int | None = None
    last_speed_kmh: Decimal | None = None
    accuracy_m: int | None = None
    quality: str
    created_at: datetime


class GpsDeviceCreated(BaseModel):
    device: GpsDeviceResponse
    # Показывается один раз при выдаче; в БД хранится только sha256.
    token: str | None = None


class GpsDeviceCreateRequest(BaseModel):
    device_number: str = Field(min_length=1, max_length=32)
    label: str | None = Field(default=None, max_length=120)
    vehicle_id: uuid.UUID | None = None
    sim_phone: str | None = Field(default=None, max_length=20)
    notes: str | None = None
    # Токен нужен только прошивкам, которые умеют его слать.
    with_token: bool = False


class GpsDeviceUpdateRequest(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    vehicle_id: uuid.UUID | None = None
    sim_phone: str | None = Field(default=None, max_length=20)
    notes: str | None = None
    is_active: bool | None = None
    confirm: bool = False
    rotate_token: bool = False
    drop_token: bool = False


class GpsTrackPoint(BaseModel):
    recorded_at: datetime
    lat: float
    lon: float
    sats: int
    accuracy_m: int | None = None
    speed_kmh: float | None = None


class GpsTrackSummary(BaseModel):
    points: int
    shown_points: int = 0
    distance_km: float
    moving_minutes: int
    max_speed_kmh: float | None = None
    avg_speed_kmh: float | None = None
    avg_accuracy_m: float | None = None
    first_at: datetime | None = None
    last_at: datetime | None = None


class GpsTrackResponse(BaseModel):
    points: list[GpsTrackPoint]
    summary: GpsTrackSummary


class GpsRawMessage(BaseModel):
    at: datetime
    source: str
    payload: str
    result: str
    detail: str = ""
    device: str = ""
