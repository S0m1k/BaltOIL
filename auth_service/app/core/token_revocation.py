"""Серверная ревокация access-токенов через ОБЩИЙ Redis-денилист (fail-open).

auth_service ставит метку revoked_after:{user_id}=<unix-ts> при logout / смене пароля /
деактивации. Любой access-токен с iat < этой метки считается отозванным. Все сервисы
проверяют метку в get_current_user.

ВАЖНО: каждый сервис настроен на свою логическую Redis-DB (/0../4), поэтому namespace
ревокации принудительно живёт в общей выделенной DB (15) — иначе метка, записанная
auth-сервисом, не была бы видна остальным. На любой ошибке Redis — пропускаем
(fail-open), чтобы сбой Redis не положил аутентификацию всей системы.
"""
import logging
import re
import time

import redis.asyncio as aioredis

from app.config import get_settings

log = logging.getLogger(__name__)
_settings = get_settings()

# Общая DB для всех сервисов: берём host:port из redis_url, форсим /15.
_REVOCATION_DB = 15
_base = re.sub(r"/\d+\s*$", "", _settings.redis_url.rstrip("/"))
_REVOCATION_URL = f"{_base}/{_REVOCATION_DB}"

_redis: "aioredis.Redis | None" = None


def _client() -> "aioredis.Redis":
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(_REVOCATION_URL, decode_responses=True)
    return _redis


def _key(user_id: str) -> str:
    return f"revoked_after:{user_id}"


async def is_token_revoked(user_id: str, iat) -> bool:
    """True, если токен с этим iat отозван (выпущен до метки). Fail-open."""
    if not iat:
        return False  # токены без iat (служебные/старые) ревокации не подлежат
    try:
        val = await _client().get(_key(str(user_id)))
        return bool(val) and int(iat) < int(float(val))
    except Exception:
        # Fail-open — осознанный trade-off (см. docstring модуля). Логируем на ERROR,
        # т.к. в этот момент система временно НЕ соблюдает logout/деактивацию —
        # операторам нужен алерт, а не тихий warning.
        log.error("token revocation check failed (fail-open) — revocation NOT enforced", exc_info=True)
        return False


async def revoke_user_tokens(user_id: str) -> None:
    """Отозвать все access-токены пользователя, выпущенные до текущего момента.

    TTL метки обязан покрывать МАКСИМАЛЬНУЮ жизнь токена. Сотрудники
    (admin/manager/driver) получают staff_access_token_expire_minutes (12 ч),
    и если ориентироваться на короткий клиентский TTL (15 мин), метка истекала
    бы раньше токена — отозванный staff-токен снова стал бы валиден.
    """
    max_token_minutes = max(
        getattr(_settings, "access_token_expire_minutes", 15),
        getattr(_settings, "staff_access_token_expire_minutes", 720),
    )
    ttl = max_token_minutes * 60 + 60
    try:
        await _client().set(_key(str(user_id)), int(time.time()), ex=ttl)
    except Exception:
        log.warning("token revocation set failed", exc_info=True)
