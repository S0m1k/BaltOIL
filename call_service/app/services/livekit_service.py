"""
LiveKit token generation and room management.

Tokens are JWTs signed with LIVEKIT_API_SECRET. They embed:
  - identity   — user_id (used by LiveKit to identify participants)
  - name       — display name shown to other participants
  - VideoGrants — what the user is allowed to do in the room
"""
from datetime import timedelta
from livekit import api as lkapi

from app.config import settings


def generate_room_token(
    user_id: str,
    user_name: str,
    room_name: str,
    can_publish: bool = True,
    ttl_minutes: int = 30,
) -> str:
    """Создать JWT для входа конкретного пользователя в конкретную комнату."""
    token = (
        lkapi.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(user_id)
        .with_name(user_name)
        .with_ttl(timedelta(minutes=ttl_minutes))
        .with_grants(
            lkapi.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=can_publish,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
    )
    return token.to_jwt()


async def create_room(room_name: str, empty_timeout: int = 120) -> None:
    """Создать комнату в LiveKit. Идемпотентно — повторные вызовы безопасны.

    empty_timeout — через сколько секунд после того, как комната опустеет, LiveKit её удалит.
    Исключения НЕ подавляются: вызывающий код должен знать о недоступности LiveKit.
    """
    async with lkapi.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    ) as lk:
        await lk.room.create_room(
            lkapi.CreateRoomRequest(name=room_name, empty_timeout=empty_timeout)
        )


async def delete_room(room_name: str) -> None:
    """Принудительно завершить комнату — выкинет всех участников."""
    async with lkapi.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    ) as lk:
        try:
            await lk.room.delete_room(lkapi.DeleteRoomRequest(room=room_name))
        except Exception:
            pass
