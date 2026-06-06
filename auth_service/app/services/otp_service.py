"""OTP lifecycle for SMS-based login and password reset.

Codes are generated here, stored in Redis with TTL, rate-limited here.
notification_service is a dumb SMS sender — it does not generate or validate codes.

Redis key layout:
  otp:{purpose}:{phone}       → 6-digit code, TTL 300 s
  otp:rl:last:{purpose}:{phone} → unix ts of last send, TTL 3600 s (min-interval check)
  otp:rl:hour:{purpose}:{phone} → counter of sends in last hour (hourly cap)

purpose must be one of {"login", "reset"}.
"""
import hmac
import logging
import secrets
import time

import redis.asyncio as aioredis

from app.config import get_settings

log = logging.getLogger(__name__)

_OTP_TTL = 300           # code valid for 5 minutes
_RL_MIN_INTERVAL = 60    # minimum seconds between consecutive sends
_RL_HOUR_CAP = 5         # max sends per hour per (phone, purpose)
_RL_HOUR_TTL = 3600      # hour window TTL


def _code_key(purpose: str, phone: str) -> str:
    return f"otp:{purpose}:{phone}"


def _rl_last_key(purpose: str, phone: str) -> str:
    return f"otp:rl:last:{purpose}:{phone}"


def _rl_hour_key(purpose: str, phone: str) -> str:
    return f"otp:rl:hour:{purpose}:{phone}"


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def issue_code(purpose: str, phone: str) -> str | None:
    """Generate and store a 6-digit OTP.

    Returns the code string on success, or None if rate-limited.
    Callers must check for None before sending SMS.
    """
    r = await _get_redis()
    try:
        now = time.time()

        # Minimum interval between sends
        last_str = await r.get(_rl_last_key(purpose, phone))
        if last_str:
            elapsed = now - float(last_str)
            if elapsed < _RL_MIN_INTERVAL:
                log.info(
                    "otp.issue_code: rate-limited (min interval) purpose=%s phone=%s",
                    purpose, phone,
                )
                return None

        # Hourly cap
        hour_count_str = await r.get(_rl_hour_key(purpose, phone))
        if hour_count_str and int(hour_count_str) >= _RL_HOUR_CAP:
            log.info(
                "otp.issue_code: rate-limited (hourly cap) purpose=%s phone=%s",
                purpose, phone,
            )
            return None

        # Generate code
        code = f"{secrets.randbelow(1_000_000):06d}"

        # Store code + update rate-limit keys atomically via pipeline
        async with r.pipeline(transaction=True) as pipe:
            pipe.set(_code_key(purpose, phone), code, ex=_OTP_TTL)
            pipe.set(_rl_last_key(purpose, phone), str(now), ex=_RL_HOUR_TTL)
            pipe.incr(_rl_hour_key(purpose, phone))
            pipe.expire(_rl_hour_key(purpose, phone), _RL_HOUR_TTL)
            await pipe.execute()

        log.info("otp.issue_code: issued purpose=%s phone=%s", purpose, phone)
        return code

    finally:
        await r.aclose()


async def verify_code(purpose: str, phone: str, code: str) -> bool:
    """Verify an OTP. Returns True and deletes the code on success, False otherwise.

    Uses hmac.compare_digest for constant-time comparison to prevent
    timing-based enumeration of valid codes.
    """
    r = await _get_redis()
    try:
        stored = await r.get(_code_key(purpose, phone))
        if not stored:
            return False
        # Constant-time compare — both strings are short ASCII digits,
        # encode to bytes as required by hmac.compare_digest.
        if not hmac.compare_digest(stored.encode(), code.strip().encode()):
            return False
        # Correct code — delete immediately to prevent replay
        await r.delete(_code_key(purpose, phone))
        log.info("otp.verify_code: verified purpose=%s phone=%s", purpose, phone)
        return True

    finally:
        await r.aclose()
