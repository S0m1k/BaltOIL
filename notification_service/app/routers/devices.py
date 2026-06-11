"""Регистрация push-токенов мобильных устройств.

POST   /api/v1/devices          — зарегистрировать/обновить токен текущего юзера
DELETE /api/v1/devices/{token}  — удалить токен (logout на устройстве)
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import TokenUser, get_current_user
from app.database import get_db
from app.models.device_token import DeviceToken

log = logging.getLogger(__name__)

router = APIRouter()

# Защита от мусора: у одного юзера не может накопиться больше N устройств —
# старые (по updated_at) вытесняются при регистрации сверх лимита.
_MAX_DEVICES_PER_USER = 10


class DeviceRegisterRequest(BaseModel):
    platform: str = Field(..., description="android | ios")
    token: str = Field(..., min_length=10, max_length=512)

    @field_validator("platform")
    @classmethod
    def platform_known(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("android", "ios"):
            raise ValueError("platform должен быть android или ios")
        return v


@router.post("", status_code=201)
async def register_device(
    data: DeviceRegisterRequest,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = (
        await db.execute(select(DeviceToken).where(DeviceToken.token == data.token))
    ).scalar_one_or_none()

    if existing:
        # Перелогин на том же устройстве: токен переходит новому владельцу.
        existing.user_id = actor.id
        existing.platform = data.platform
    else:
        db.add(DeviceToken(user_id=actor.id, platform=data.platform, token=data.token))

    # Вытесняем самые старые устройства сверх лимита.
    rows = (
        await db.execute(
            select(DeviceToken)
            .where(DeviceToken.user_id == actor.id)
            .order_by(DeviceToken.updated_at.desc())
        )
    ).scalars().all()
    for stale in rows[_MAX_DEVICES_PER_USER:]:
        await db.delete(stale)

    await db.commit()
    return {"registered": True}


@router.delete("/{token}", status_code=204)
async def unregister_device(
    token: str,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Удалять можно только свои токены — чужой token молча игнорируется.
    await db.execute(
        delete(DeviceToken).where(
            DeviceToken.token == token, DeviceToken.user_id == actor.id
        )
    )
    await db.commit()
