"""Схемы ёмкостей хранения топлива (правки 2026-07-14)."""
import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class TankCreate(BaseModel):
    """Создать ёмкость (только admin)."""
    name: str = Field(..., min_length=1, max_length=100)
    fuel_type: str = Field(..., min_length=1, max_length=50)
    initial_volume: float = Field(0, ge=0, description="Начальный остаток, л")
    counter: int = Field(0, ge=0, le=999_999, description="Начальное показание счётчика")


class TankUpdate(BaseModel):
    """Переименование / смена вида топлива / скрытие (только admin)."""
    name: str | None = Field(None, min_length=1, max_length=100)
    fuel_type: str | None = Field(None, min_length=1, max_length=50)
    is_active: bool | None = None


class TankAdjust(BaseModel):
    """Корректировка админа: задать точный остаток и/или показание счётчика."""
    volume: float | None = Field(None, description="Новый остаток, л (может быть отрицательным)")
    counter: int | None = Field(None, ge=0, le=999_999, description="Новое показание счётчика")
    notes: str | None = Field(None, max_length=500)


class TankArrival(BaseModel):
    """Приход топлива в ёмкость (водитель/менеджер/админ)."""
    volume: float = Field(..., gt=0, description="Сколько добавили, л")
    notes: str | None = Field(None, max_length=500)


class TankIssue(BaseModel):
    """Выдача по заявке: водитель вводит новое показание счётчика.

    Списанные литры = counter_after − текущий счётчик (с переполнением
    через 999999). volume_hint — фактический объём доставки для сверки.
    """
    counter_after: int = Field(..., ge=0, le=999_999)
    order_id: uuid.UUID | None = None
    order_number: str | None = Field(None, max_length=30)
    volume_hint: float | None = Field(None, gt=0)
    notes: str | None = Field(None, max_length=500)


class TankTransfer(BaseModel):
    """Перелив между ёмкостями (любые роли склада, любые виды топлива)."""
    from_tank_id: uuid.UUID
    to_tank_id: uuid.UUID
    volume: float = Field(..., gt=0)
    notes: str | None = Field(None, max_length=500)


class TankResponse(BaseModel):
    id: uuid.UUID
    name: str
    fuel_type: str
    fuel_label: str | None = None
    current_volume: float
    counter: int
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class TankTxResponse(BaseModel):
    id: uuid.UUID
    tank_id: uuid.UUID
    tank_name: str | None = None
    kind: str
    volume: float
    counter_before: int | None
    counter_after: int | None
    order_id: uuid.UUID | None
    order_number: str | None
    peer_tank_id: uuid.UUID | None
    peer_tank_name: str | None = None
    actor_id: uuid.UUID
    actor_name: str | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
