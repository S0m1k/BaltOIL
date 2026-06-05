from pydantic import BaseModel, Field


class FuelTypeInfo(BaseModel):
    """Запись каталога топлива, возвращаемая публичным и внутренним API."""
    code: str
    label: str
    is_winter: bool
    is_active: bool
    sort_order: int

    model_config = {"from_attributes": True}


class FuelTypeCreate(BaseModel):
    """Создать новый вид топлива (только admin)."""
    code: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    label: str = Field(..., min_length=1, max_length=100)
    is_winter: bool = False
    sort_order: int = 0


class FuelTypeUpdate(BaseModel):
    """Обновить запись каталога (только admin). Все поля опциональны."""
    label: str | None = Field(None, min_length=1, max_length=100)
    is_winter: bool | None = None
    sort_order: int | None = None
    is_active: bool | None = None
