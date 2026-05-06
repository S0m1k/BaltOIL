import uuid
from dataclasses import dataclass
from typing import Annotated
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from app.config import get_settings
from app.core.exceptions import AuthError, ForbiddenError

settings = get_settings()
bearer_scheme = HTTPBearer(auto_error=False)

ROLE_ADMIN   = "admin"
ROLE_MANAGER = "manager"
ROLE_DRIVER  = "driver"
ROLE_CLIENT  = "client"


@dataclass
class TokenUser:
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
            raise JWTError()
    except JWTError:
        raise AuthError("Недействительный или истёкший токен")

    user_id = payload.get("sub")
    role    = payload.get("role")
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
