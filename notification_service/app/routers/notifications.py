import asyncio
import uuid
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from app.database import get_db
from app.core.dependencies import TokenUser, get_current_user, get_current_user_sse
from app.schemas.notification import NotificationResponse, PublishRequest
from app.services.notification_service import (
    create_notifications,
    list_notifications,
    mark_read,
    mark_all_read,
    notif_to_json,
)
from app.config import settings

router = APIRouter()


def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


# ─── REST ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[NotificationResponse])
async def get_notifications(
    limit: int = 30,
    unread_only: bool = False,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await list_notifications(db, actor.id, limit=limit, unread_only=unread_only)


@router.post("/{notif_id}/read", status_code=204)
async def read_one(
    notif_id: uuid.UUID,
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await mark_read(db, notif_id, actor.id)


@router.post("/read-all", status_code=204)
async def read_all(
    actor: TokenUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await mark_all_read(db, actor.id)


# ─── Internal publish (called by other services) ─────────────────────────────

def _require_internal(x_internal_secret: str = Header(..., alias="X-Internal-Secret")) -> None:
    if x_internal_secret != settings.internal_api_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/internal/publish", status_code=201, dependencies=[Depends(_require_internal)])
async def publish(
    data: PublishRequest,
    db: AsyncSession = Depends(get_db),
):
    notifications = await create_notifications(db, data)
    r = _redis()
    try:
        for n in notifications:
            channel = f"notifs:{n.user_id}"
            await r.publish(channel, notif_to_json(n))
    finally:
        await r.aclose()
    return {"created": len(notifications)}


# ─── SSE stream ──────────────────────────────────────────────────────────────

@router.get("/stream")
async def sse_stream(
    request: Request,
    actor: TokenUser = Depends(get_current_user_sse),
):
    channel = f"notifs:{actor.id}"

    async def event_generator():
        r = _redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(channel)
        try:
            # Send a keep-alive comment immediately so the browser connection is established
            yield ": keep-alive\n\n"
            while True:
                if await request.is_disconnected():
                    break
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=25)
                if msg and msg["type"] == "message":
                    data = msg["data"]
                    yield f"data: {data}\n\n"
                else:
                    # heartbeat every ~25 s
                    yield ": ping\n\n"
                await asyncio.sleep(0.1)
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
            await r.aclose()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
