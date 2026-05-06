"""Publish domain events to Redis so other services (notification_service) can react."""
import json
import logging
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger(__name__)


async def publish_order_event(payload: dict) -> None:
    """Fire-and-forget publish to events:orders channel."""
    try:
        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        try:
            await r.publish("events:orders", json.dumps(payload))
        finally:
            await r.aclose()
    except Exception:
        logger.exception("Failed to publish order event")
