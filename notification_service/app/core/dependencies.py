import uuid
from dataclasses import dataclass
from fastapi import Depends, Header, Query
from jose import JWTError, jwt
from app.config import settings
from fastapi import HTTPException
from app.core.token_revocation import is_token_revoked


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
    token = authorization[7:]
    actor = _decode(token)
    try:
        iat = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"]).get("iat")
    except Exception:
        iat = None
    if await is_token_revoked(str(actor.id), iat):
        raise HTTPException(status_code=401, detail="Session ended, log in again")
    return actor


async def get_current_user_sse(token: str = Query(...)) -> TokenUser:
    """For SSE — token passed as query param."""
    return _decode(token)
