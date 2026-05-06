import uuid
from dataclasses import dataclass
from fastapi import Depends, Header, Query
from jose import JWTError, jwt
from app.config import settings
from fastapi import HTTPException


@dataclass
class TokenUser:
    id: uuid.UUID
    role: str
    name: str


def _decode(token: str) -> TokenUser:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
        return TokenUser(
            id=uuid.UUID(payload["sub"]),
            role=payload["role"],
            name=payload.get("name", ""),
        )
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(authorization: str = Header(...)) -> TokenUser:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return _decode(authorization[7:])


async def get_current_user_sse(token: str = Query(...)) -> TokenUser:
    """For SSE — token passed as query param."""
    return _decode(token)
