import uuid
from datetime import datetime
from pydantic import BaseModel
from app.models.conversation import ConversationType
from .message import MessageResponse


class ParticipantResponse(BaseModel):
    user_id: uuid.UUID
    user_role: str
    last_read_at: datetime | None
    joined_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreateRequest(BaseModel):
    type: ConversationType = ConversationType.CLIENT_SUPPORT
    order_id: uuid.UUID | None = None
    title: str | None = None
    # Дополнительные участники (их UUID), создатель добавляется автоматически
    participant_ids: list[uuid.UUID] = []


class ConversationListResponse(BaseModel):
    id: uuid.UUID
    type: ConversationType
    order_id: uuid.UUID | None
    title: str | None
    created_by_id: uuid.UUID
    created_by_role: str
    unread_count: int = 0
    last_message: MessageResponse | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: uuid.UUID
    type: ConversationType
    order_id: uuid.UUID | None
    title: str | None
    created_by_id: uuid.UUID
    created_by_role: str
    participants: list[ParticipantResponse] = []
    messages: list[MessageResponse] = []
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
