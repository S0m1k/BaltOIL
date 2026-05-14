"""
WebSocket endpoint with Redis Pub/Sub broadcasting.

Flow:
  1. Client connects: ws://host/ws/{conv_id}?token=<JWT>
  2. Server validates JWT, checks conversation access.
  3. Server subscribes to Redis channel "chat:{conv_id}".
  4. On incoming WS message → persist to DB → publish to Redis.
  5. Redis listener task forwards published messages to all connected WS clients in this process.
"""

import asyncio
import json
import logging
import uuid
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

log = logging.getLogger(__name__)
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.core.dependencies import _decode_token
from app.core.exceptions import AuthError, ForbiddenError
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.conversation_service import _check_access
from app.services.message_service import send_message
from app.config import settings

router = APIRouter(tags=["websocket"])

# In-process registry: conv_id → set of WebSocket connections
_connections: dict[str, set[WebSocket]] = {}


async def _get_redis():
    import redis.asyncio as aioredis
    return aioredis.from_url(settings.redis_url, decode_responses=True)


@router.websocket("/ws/{conv_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    conv_id: uuid.UUID,
    token: str = Query(...),
):
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
        except (ForbiddenError, Exception):
            await websocket.close(code=4003)
            return

    await websocket.accept()

    channel = f"chat:{conv_id}"
    conv_key = str(conv_id)

    if conv_key not in _connections:
        _connections[conv_key] = set()
    _connections[conv_key].add(websocket)

    redis = await _get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel)

    async def redis_listener():
        """Forward Redis messages to this WebSocket."""
        try:
            async for raw in pubsub.listen():
                if raw["type"] == "message":
                    try:
                        await websocket.send_text(raw["data"])
                    except Exception:
                        break
        except Exception:
            log.exception("Redis listener error for conv %s", conv_id)

    listener_task = asyncio.create_task(redis_listener())

    try:
        while True:
            text = await websocket.receive_text()

            # Validate message length (mirrors Pydantic schema max_length=4000)
            if len(text) > 4000:
                await websocket.send_text(json.dumps({"error": "Сообщение слишком длинное (макс. 4000 символов)"}))
                continue

            # Persist message to DB
            async with AsyncSessionLocal() as db:
                msg = await send_message(db, conv_id, text, actor)

            payload = json.dumps({
                "id": str(msg.id),
                "conversation_id": str(msg.conversation_id),
                "sender_id": str(msg.sender_id),
                "sender_role": msg.sender_role,
                "sender_name": msg.sender_name,
                "text": msg.text,
                "created_at": msg.created_at.isoformat(),
            })

            # Broadcast via Redis so all instances receive it
            await redis.publish(channel, payload)

    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket error for conv %s", conv_id)
    finally:
        listener_task.cancel()
        _connections[conv_key].discard(websocket)
        if not _connections[conv_key]:
            del _connections[conv_key]
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis.aclose()
