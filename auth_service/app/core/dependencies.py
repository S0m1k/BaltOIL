from typing import Annotated
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User, UserRole
from app.core.security import decode_access_token
from app.core.token_revocation import is_token_revoked
from app.core.exceptions import AuthError, ForbiddenError

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if not credentials:
        raise AuthError("Токен не передан")

    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise AuthError("Недействительный или истёкший токен")

    user_id: str = payload.get("sub")
    if not user_id:
        raise AuthError("Некорректный токен")

    # Серверная ревокация (logout / смена пароля / деактивация)
    if await is_token_revoked(user_id, payload.get("iat")):
        raise AuthError("Сессия завершена, войдите снова")

    result = await db.execute(
        select(User)
        .options(selectinload(User.client_profile))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if not user or user.is_archived:
        raise AuthError("Пользователь не найден или удалён")
    if not user.is_active:
        raise AuthError("Аккаунт деактивирован")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """
    Dependency factory for role-based access control.

    Usage:
        @router.get("/admin-only")
        async def handler(user: Annotated[User, Depends(require_roles(UserRole.ADMIN))]):
            ...
    """
    async def _check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise ForbiddenError(
                f"Требуется одна из ролей: {', '.join(r.value for r in roles)}"
            )
        return user

    return _check


def trusted_client_ip(request: Request) -> str:
    """Return the real client IP set by nginx via X-Real-IP.

    nginx sets X-Real-IP = $remote_addr (the actual TCP peer of nginx).
    Because backend services have no host port and are only reachable through
    nginx, this header is trustworthy. Falls back to direct peer for local dev.
    """
    return request.headers.get("X-Real-IP") or (
        request.client.host if request.client else "0.0.0.0"
    )


def _sanitize_user_agent(ua: str | None) -> str | None:
    """Защита от log injection: убираем управляющие символы (CR/LF и пр.) и
    ограничиваем длину — User-Agent целиком контролируется клиентом."""
    if not ua:
        return ua
    cleaned = "".join(ch for ch in ua if ch.isprintable())
    return cleaned[:512]


def get_request_meta(request: Request) -> dict:
    """Extracts IP and user-agent for audit logging."""
    return {
        "ip_address": trusted_client_ip(request),
        "user_agent": _sanitize_user_agent(request.headers.get("User-Agent")),
    }
