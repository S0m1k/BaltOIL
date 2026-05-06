from fastapi import APIRouter
from app.models.order import FuelType
from app.schemas.fuel_type import FuelTypeInfo, FUEL_TYPE_META
from app.core.dependencies import CurrentUser

router = APIRouter(prefix="/fuel-types", tags=["fuel-types"])


@router.get("", response_model=list[FuelTypeInfo])
async def list_fuel_types(_: CurrentUser):
    return [
        FuelTypeInfo(code=ft, **FUEL_TYPE_META[ft])
        for ft in FuelType
    ]
