import uuid
from datetime import datetime
from pydantic import BaseModel
from app.models.call import CallStatus


class StartCallRequest(BaseModel):
    """Инициировать звонок по конкретному диалогу.

    Сервер сам определит список участников из chat_service,
    исключив инициатора.
    """
    conversation_id: uuid.UUID


class TokenRequest(BaseModel):
    """Запросить токен для входа в существующую комнату (например, при ответе на звонок)."""
    room_name: str


class CallParticipantResponse(BaseModel):
    user_id: uuid.UUID
    user_name: str
    user_role: str
    joined_at: datetime | None
    left_at: datetime | None

    model_config = {"from_attributes": True}


class CallResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    room_name: str
    status: CallStatus
    initiated_by_id: uuid.UUID
    initiated_by_name: str
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    participants: list[CallParticipantResponse] = []

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Ответ на запрос токена — всё нужное для подключения браузера к комнате."""
    call_id: uuid.UUID
    room_name: str
    token: str
    livekit_url: str
