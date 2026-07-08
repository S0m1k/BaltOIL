import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.core.dependencies import CurrentUser
from app.schemas.client_object import ClientObjectCreateRequest, ClientObjectResponse
from app.services import client_object_service

router = APIRouter(prefix="/client-objects", tags=["client-objects"])


@router.get("", response_model=list[ClientObjectResponse])
async def list_client_objects(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    client_id: uuid.UUID | None = Query(None),
):
    return await client_object_service.list_objects(db, current_user, client_id)


@router.post("", response_model=ClientObjectResponse, status_code=201)
async def create_client_object(
    data: ClientObjectCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    return await client_object_service.create_object(db, data, current_user)


@router.delete("/{object_id}", status_code=204)
async def delete_client_object(
    object_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    await client_object_service.delete_object(db, object_id, current_user)
