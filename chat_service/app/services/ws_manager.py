"""
Lightweight online-presence tracker backed by Redis.

Each WS connection calls register() on connect and unregister() on disconnect.
The Redis key `ws:online:{user_id}` holds a unix timestamp (seconds) and
expires automatically after 300 seconds (5 min) to handle crash/silent-disconnect.

A user is considered "online" if the key exists AND the stored timestamp is
not older than 5 minutes.  notification_service uses this to decide whether to
send an email for a chat message or call.
"""
import time
import logging
import uuid

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_KEY_TTL = 300  # seconds — matches the "offline >5min" trigger window


def _key(user_id: uuid.UUID) -> str:
    return f"ws:online:{user_id}"


async def register(redis: aioredis.Redis, user_id: uuid.UUID) -> None:
    """Mark user as online.  Call on every new WS connection."""
    try:
        await redis.set(_key(user_id), int(time.time()), ex=_KEY_TTL)
    except Exception:
        logger.warning("ws_manager.register failed for user %s", user_id, exc_info=True)


async def unregister(redis: aioredis.Redis, user_id: uuid.UUID) -> None:
    """Remove online marker when the LAST connection for this user closes.

    If the user still has other open connections in this process the key is
    left intact — we do not track per-connection granularity in Redis.

    NOTE: In a multi-process / multi-replica setup the process-level
    _connections dict in websocket.py is sufficient to decide "last connection
    in this process".  Cross-process presence is handled by the key TTL.
    """
    try:
        await redis.delete(_key(user_id))
    except Exception:
        logger.warning("ws_manager.unregister failed for user %s", user_id, exc_info=True)


async def is_online(redis: aioredis.Redis, user_id: uuid.UUID) -> bool:
    """Return True if the user has an active WS connection (key present and fresh)."""
    try:
        val = await redis.get(_key(user_id))
        if val is None:
            return False
        ts = int(val)
        return (time.time() - ts) < _KEY_TTL
    except Exception:
        logger.warning("ws_manager.is_online failed for user %s", user_id, exc_info=True)
        # Fail-open: treat as online so we don't spam emails on Redis outage
        return True
