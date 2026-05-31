import hashlib
import secrets
from datetime import datetime, timedelta, timezone
import bcrypt
from jose import jwt, JWTError
from app.config import get_settings

settings = get_settings()


# --- Password ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    # bcrypt.checkpw raises ValueError on a malformed hash (truncated, wrong prefix, etc.).
    # Treat that as "wrong credentials" rather than letting it bubble up as HTTP 500.
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


# --- Access Token (JWT) ---

def create_access_token(user_id: str, role: str, name: str = "") -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user_id,
        "role": role,
        "name": name,
        "iat": now,            # нужен для серверной ревокации (logout/смена пароля/деактивация)
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises JWTError if invalid or expired."""
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    if payload.get("type") != "access":
        raise JWTError("Wrong token type")
    return payload


# --- Refresh Token (opaque) ---

def generate_refresh_token() -> str:
    """Generates a cryptographically secure random token (URL-safe)."""
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    """SHA-256 hash stored in DB; raw token sent to client."""
    return hashlib.sha256(token.encode()).hexdigest()


def refresh_token_expires_at() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
