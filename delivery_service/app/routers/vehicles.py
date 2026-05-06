import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser
from app.schemas.vehicle import VehicleResponse, VehicleCreateRequest, VehicleUpdateRequest
from app.services import vehicle_service

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


@router.get("", response_model=list[VehicleResponse])
async def list_vehicles(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    include_inactive: bool = Query(False),
):
    return await vehicle_service.list_vehicles(db, current_user, include_inactive=include_inactive)


@router.post("", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    data: VehicleCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await vehicle_service.create_vehicle(db, data, current_user)


@router.get("/{vehicle_id}", response_model=VehicleResponse)
async def get_vehicle(
    vehicle_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await vehicle_service.get_vehicle(db, vehicle_id)


@router.patch("/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: uuid.UUID,
    data: VehicleUpdateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await vehicle_service.update_vehicle(db, vehicle_id, data, current_user)


@router.delete("/{vehicle_id}", status_code=204)
async def archive_vehicle(
    vehicle_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await vehicle_service.archive_vehicle(db, vehicle_id, current_user)
