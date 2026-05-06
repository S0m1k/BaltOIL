import uuid
from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.config import get_settings
from app.core.exceptions import AuthError, ForbiddenError

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class TokenUser:
    """Данные пользователя, извлечённые из JWT — без обращения к auth_service."""
    id: uuid.UUID
    role: str


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
            raise JWTError("Wrong token type")
    except JWTError:
        raise AuthError("Недействительный или истёкший токен")

    user_id = payload.get("sub")
    role = payload.get("role")
    if not user_id or not role:
        raise AuthError("Некорректный токен")

    return TokenUser(id=uuid.UUID(user_id), role=role)


CurrentUser = Annotated[TokenUser, Depends(get_current_user)]


def require_roles(*roles: str):
    async def _check(user: CurrentUser) -> TokenUser:
        if user.role not in roles:
            raise ForbiddenError(f"Требуется одна из ролей: {', '.join(roles)}")
        return user
    return _check


def get_request_meta(request: Request) -> dict:
    forwarded_for = request.headers.get("X-Forwarded-For")
    ip = forwarded_for.split(",")[0].strip() if forwarded_for else request.client.host
    return {"ip_address": ip, "user_agent": request.headers.get("User-Agent")}
