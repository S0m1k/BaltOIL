"""Shared slowapi Limiter for auth_service.

Uses Redis storage so limits are enforced across multiple uvicorn workers.
Key function reads X-Real-IP set by nginx (the actual client IP).
"""
from slowapi import Limiter
from app.core.dependencies import trusted_client_ip
from app.config import get_settings

limiter = Limiter(
    key_func=trusted_client_ip,
    storage_uri=get_settings().redis_url,
    strategy="fixed-window",
)
