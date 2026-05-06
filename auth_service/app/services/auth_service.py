from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.core.security import (
    verify_password,
    create_access_token,
    generate_refresh_token,
    hash_token,
    refresh_token_expires_at,
)
from app.core.exceptions import AuthError
from app.schemas.auth import TokenResponse
from app.services.audit_service import log_action


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    result = await db.execute(select(User).where(User.email == email.lower().strip()))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        raise AuthError("Неверный email или пароль")

    if user.is_archived:
        raise AuthError("Аккаунт удалён")
    if not user.is_active:
        raise AuthError("Аккаунт деактивирован. Обратитесь к администратору")

    access_token = create_access_token(str(user.id), user.role.value, user.full_name)
    raw_refresh = generate_refresh_token()

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=refresh_token_expires_at(),
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    await log_action(
        db,
        action="user.login",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": email},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)


async def refresh_tokens(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    token_hash = hash_token(raw_refresh_token)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712
            RefreshToken.expires_at > now,
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise AuthError("Refresh token недействителен или истёк")

    # Rotate: revoke old, issue new
    db_token.is_revoked = True

    user_result = await db.execute(select(User).where(User.id == db_token.user_id))
    user = user_result.scalar_one_or_none()

    if not user or user.is_archived or not user.is_active:
        raise AuthError("Пользователь недоступен")

    access_token = create_access_token(str(user.id), user.role.value, user.full_name)
    new_raw_refresh = generate_refresh_token()

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_raw_refresh),
        expires_at=refresh_token_expires_at(),
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    await log_action(
        db,
        action="user.token_refresh",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        ip_address=ip_address,
    )

    return TokenResponse(access_token=access_token, refresh_token=new_raw_refresh)


async def logout(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    actor_id,
) -> None:
    token_hash = hash_token(raw_refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == actor_id,
        )
    )
    db_token = result.scalar_one_or_none()
    if db_token:
        db_token.is_revoked = True

    await log_action(
        db,
        action="user.logout",
        actor_id=actor_id,
        entity_type="user",
        entity_id=actor_id,
    )


async def logout_all(db: AsyncSession, *, user_id) -> None:
    """Revoke all refresh tokens for the user (e.g. on password change)."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
    )
    for token in result.scalars().all():
        token.is_revoked = True
