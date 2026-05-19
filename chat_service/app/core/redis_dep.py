"""FastAPI dependency for the app-level Redis pool.

The pool is initialised in main.py lifespan and stored on app.state.redis.
All request handlers that need Redis should depend on get_redis rather than
creating their own connections — this keeps TCP connections shared and avoids
the per-request connect/close overhead.
"""
import redis.asyncio as aioredis
from fastapi import Request


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis
