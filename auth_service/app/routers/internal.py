"""Internal endpoints for service-to-service communication.

These routes are NOT exposed through nginx — they are only accessible
on the Docker internal network. Auth is done via X-Internal-Secret header
(HMAC-safe comparison, same secret used by delivery/notification services).
"""
import hmac
import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.models.client_profile import ClientProfile

router = APIRouter(prefix="/internal", tags=["internal"])
settings = get_settings()


def _require_internal(
    x_internal_secret: Annotated[str, Header(alias="X-Internal-Secret")],
) -> None:
    if not hmac.compare_digest(x_internal_secret, settings.internal_api_secret):
        raise HTTPException(status_code=403, detail="Invalid internal secret")


class ClientContextResponse(BaseModel):
    user_id: uuid.UUID
    client_type: str           # "individual" | "company"
    credit_allowed: bool
    tariff_id: uuid.UUID | None  # None → order_service uses default tariff


@router.get(
    "/clients/{client_id}/context",
    response_model=ClientContextResponse,
    dependencies=[Depends(_require_internal)],
)
async def get_client_context(
    client_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ClientContextResponse:
    """Return client_type, credit_allowed, tariff_id for order_service pricing checks."""
    result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == client_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Client profile not found")

    return ClientContextResponse(
        user_id=client_id,
        client_type=profile.client_type.value,
        credit_allowed=profile.credit_allowed,
        tariff_id=profile.tariff_id,
    )


@router.get(
    "/users-by-role",
    response_model=list[uuid.UUID],
    dependencies=[Depends(_require_internal)],
)
async def get_users_by_role(
    roles: str,  # comma-separated, e.g. "manager,admin"
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[uuid.UUID]:
    """Return user IDs for all active users with the given roles (for notification fanout)."""
    role_list = [r.strip() for r in roles.split(",") if r.strip()]
    result = await db.execute(
        select(User.id).where(
            User.role.in_(role_list),
            User.is_active == True,  # noqa: E712
        )
    )
    return [row[0] for row in result.all()]
