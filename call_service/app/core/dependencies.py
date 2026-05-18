import uuid
from dataclasses import dataclass
from fastapi import Header
from jose import JWTError, jwt
from app.config import settings
from app.core.exceptions import AuthError


@dataclass
class TokenUser:
    id: uuid.UUID
    role: str
    name: str


def _decode_token(token: str) -> TokenUser:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = payload.get("sub")
        role = payload.get("role")
        name = payload.get("name", "")
        if not user_id or not role:
            raise AuthError("Invalid token payload")
        return TokenUser(id=uuid.UUID(user_id), role=role, name=name)
    except (JWTError, ValueError):
        raise AuthError("Invalid or expired token")


async def get_current_user(authorization: str = Header(...)) -> TokenUser:
    if not authorization.startswith("Bearer "):
        raise AuthError("Missing Bearer token")
    return _decode_token(authorization[7:])
