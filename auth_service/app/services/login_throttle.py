"""Per-email login throttle using Redis.

Tracks failed login attempts per (normalised) email and enforces exponential
backoff. The throttle applies whether or not the email exists — that makes the
blocking behaviour identical for valid and invalid accounts so an attacker
cannot distinguish "this email is registered" from "wrong password" by watching
which addresses get blocked.

Backoff schedule (cumulative failures → block duration):
  5  fails  →  60 s
  10 fails  →  300 s   (5 min)
  20 fails  →  1 800 s (30 min)
  30+ fails →  7 200 s (2 h)

Counters expire after 1 hour of inactivity so a legitimate user who mistyped
their password several times is not permanently penalised.
"""

import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

_BACKOFF: list[tuple[int, int]] = [(5, 60), (10, 300), (20, 1800), (30, 7200)]
_FAIL_TTL = 3600  # reset fail counter after 1 h of no attempts


def _fail_key(email: str) -> str:
    return f"login_fail:{email}"


def _block_key(email: str) -> str:
    return f"login_block:{email}"


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


async def check_blocked(email: str) -> Optional[int]:
    """Return seconds remaining in the block, or None if not blocked."""
    r = await _get_redis()
    try:
        until = await r.get(_block_key(email))
        if until:
            remaining = int(float(until) - time.time())
            if remaining > 0:
                return remaining
        return None
    finally:
        await r.aclose()


async def record_failure(email: str) -> None:
    """Increment failure counter and set/extend block if threshold crossed."""
    r = await _get_redis()
    try:
        n = await r.incr(_fail_key(email))
        if n == 1:
            await r.expire(_fail_key(email), _FAIL_TTL)
        # Apply the longest matching threshold
        for threshold, block_secs in reversed(_BACKOFF):
            if n >= threshold:
                block_until = time.time() + block_secs
                await r.set(_block_key(email), block_until, ex=block_secs + 60)
                break
    finally:
        await r.aclose()


async def reset(email: str) -> None:
    """Clear throttle state on successful login."""
    r = await _get_redis()
    try:
        await r.delete(_fail_key(email), _block_key(email))
    finally:
        await r.aclose()
