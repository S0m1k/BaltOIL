import uuid
from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt
from app.config import get_settings
from app.core.exceptions import AuthError, ForbiddenError
from app.core.token_revocation import is_token_revoked

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class TokenUser:
    """Данные пользователя, извлечённые из JWT — без обращения к auth_service."""
    id: uuid.UUID
    role: str
    token: str = ""  # raw JWT — нужен для inter-service calls


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenUser:
    if not credentials:
        raise AuthError("Токен не передан")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access":
            raise jwt.InvalidTokenError("Wrong token type")
    except jwt.PyJWTError:
        raise AuthError("Недействительный или истёкший токен")

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or not role:
        raise AuthError("Некорректный токен")

    if await is_token_revoked(user_id, payload.get("iat")):
        raise AuthError("Сессия завершена, войдите снова")

    return TokenUser(id=uuid.UUID(user_id), role=role, token=credentials.credentials)


CurrentUser = Annotated[TokenUser, Depends(get_current_user)]


def require_roles(*roles: str):
    async def _check(user: CurrentUser) -> TokenUser:
        if user.role not in roles:
            raise ForbiddenError(f"Требуется одна из ролей: {', '.join(roles)}")
        return user
    return _check


def get_request_meta(request: Request) -> dict:
    # X-Real-IP проставляет nginx ($remote_addr) — клиент не подделает.
    # X-Forwarded-For не используем: его первый элемент клиент-управляем (спуф IP в аудите).
    ip = request.headers.get("X-Real-IP") or (request.client.host if request.client else None)
    return {"ip_address": ip, "user_agent": request.headers.get("User-Agent")}
