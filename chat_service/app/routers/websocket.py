"""
WebSocket endpoint with Redis Pub/Sub broadcasting.

Flow:
  1. Client connects: ws://host/ws/{conv_id}?token=<JWT>
  2. Server validates JWT, checks conversation access.
  3. Server registers the WS in the process-level _connections map.
  4. A single Redis pubsub listener per (conv_id, process) fans messages out to
     all registered WebSocket connections in memory — no per-client subscription.
  5. On incoming WS message → persist to DB → publish to Redis → fan-out.
"""

import asyncio
import json
import logging
import uuid
import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.core.dependencies import _decode_token
from app.core.exceptions import AuthError, ForbiddenError
from app.models.conversation import Conversation
from app.services.conversation_service import _check_access
from app.services.message_service import send_message
from app.services import ws_manager

router = APIRouter(tags=["websocket"])

# ── Process-level state ────────────────────────────────────────────────────────

# conv_key → set of open WebSocket connections for this process
_connections: dict[str, set[WebSocket]] = {}

# conv_key → running asyncio Task that listens on Redis and fans out to _connections
_subscriptions: dict[str, asyncio.Task] = {}

# Lock ensures at most one listener task is started per conv_key
_sub_lock = asyncio.Lock()

_WS_CONN_LIMIT = 10   # new connections / 60 s per IP


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_ws_connect_rate(redis: aioredis.Redis, ip: str) -> bool:
    """Return False if the IP has opened too many connections recently."""
    key = f"wsconn:{ip}"
    n = await redis.incr(key)
    if n == 1:
        await redis.expire(key, 60)
    return n <= _WS_CONN_LIMIT


async def _listen(redis: aioredis.Redis, conv_key: str) -> None:
    """Single process-level listener: subscribes to Redis and fans out to sockets."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"chat:{conv_key}")
    try:
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            data = raw["data"]
            dead: set[WebSocket] = set()
            for ws in list(_connections.get(conv_key, ())):
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.add(ws)
            for ws in dead:
                _connections[conv_key].discard(ws)
            # Stop listening when no clients remain
            if not _connections.get(conv_key):
                break
    except asyncio.CancelledError:
        pass
    except Exception:
        log.exception("Redis pubsub listener error for conv %s", conv_key)
    finally:
        await pubsub.unsubscribe(f"chat:{conv_key}")
        await pubsub.aclose()
        _subscriptions.pop(conv_key, None)


async def _ensure_subscription(redis: aioredis.Redis, conv_key: str) -> None:
    """Start a fan-out listener for conv_key if one isn't already running."""
    async with _sub_lock:
        task = _subscriptions.get(conv_key)
        if task and not task.done():
            return
        _subscriptions[conv_key] = asyncio.create_task(_listen(redis, conv_key))


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.websocket("/ws/{conv_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    conv_id: uuid.UUID,
    token: str = Query(...),
):
    redis: aioredis.Redis = websocket.app.state.redis

    # Per-IP connect rate limit — checked before accept()
    ip = websocket.headers.get("x-real-ip") or (
        websocket.client.host if websocket.client else "0.0.0.0"
    )
    if not await _check_ws_connect_rate(redis, ip):
        await websocket.close(code=4029)  # Too Many Requests (custom)
        return

    # Authenticate
    try:
        actor = _decode_token(token)
    except AuthError:
        await websocket.close(code=4001)
        return

    # Check conversation access
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Conversation)
            .options(selectinload(Conversation.participants))
            .where(Conversation.id == conv_id, Conversation.is_archived == False)
        )
        conv = result.scalar_one_or_none()
        if not conv:
            await websocket.close(code=4004)
            return
        try:
            _check_access(conv, actor)
        except ForbiddenError:
            await websocket.close(code=4003)
            return
        except Exception:
            log.exception("Unexpected error checking WS access for conv %s", conv_id)
            await websocket.close(code=4003)
            return

    await websocket.accept()

    conv_key = str(conv_id)
    _connections.setdefault(conv_key, set()).add(websocket)
    await _ensure_subscription(redis, conv_key)
    await ws_manager.register(redis, actor.id)

    channel = f"chat:{conv_id}"

    try:
        while True:
            text = await websocket.receive_text()

            # Validate message length (mirrors Pydantic schema max_length=4000)
            if len(text) > 4000:
                await websocket.send_text(json.dumps({"error": "Сообщение слишком длинное (макс. 4000 символов)"}))
                continue

            # Persist + rate-limit — ForbiddenError (e.g. msg rate exceeded) is
            # returned as a JSON error frame without closing the connection.
            try:
                async with AsyncSessionLocal() as db:
                    msg = await send_message(db, conv_id, text, actor, redis)
            except ForbiddenError as e:
                await websocket.send_text(json.dumps({"error": str(e)}))
                continue

            # Publish via Redis → fan-out listener delivers to all sockets
            await redis.publish(channel, json.dumps({
                "id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "sender_id": str(msg.sender_id),
                "sender_role": msg.sender_role,
                "sender_name": msg.sender_name,
                "msg_type": msg.msg_type,
                "text": msg.text,
                "metadata": msg.msg_metadata,
                "created_at": msg.created_at.isoformat(),
            }))

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket error for conv %s", conv_id)
    finally:
        _connections[conv_key].discard(websocket)
        # Remove the online marker on disconnect.  If the user simultaneously has
        # another WS open (different conv), they will re-register on the next
        # incoming message; the 300 s TTL also prevents false "offline" readings
        # for brief gaps.  This is safe for the current single-process deployment.
        await ws_manager.unregister(redis, actor.id)
        if not _connections[conv_key]:
            _connections.pop(conv_key, None)
            # Listener will stop itself when it sees no connections on next message.
            # Cancel immediately so we don't hold a Redis subscription unnecessarily.
            task = _subscriptions.get(conv_key)
            if task:
                task.cancel()
