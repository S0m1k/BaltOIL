import uuid
from datetime import datetime
from pydantic import BaseModel
from .message import MessageResponse


class ParticipantResponse(BaseModel):
    user_id: uuid.UUID
    user_role: str
    last_read_at: datetime | None
    joined_at: datetime
    full_name: str | None = None   # резолвится из auth_service
    phone: str | None = None       # телефон участника (виден в чате)

    model_config = {"from_attributes": True}


class EnsureClientManagerRequest(BaseModel):
    client_id: uuid.UUID


class ConversationListResponse(BaseModel):
    id: uuid.UUID
    kind: str
    title: str | None
    client_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    group_code: str | None = None
    created_by_id: uuid.UUID
    created_by_role: str
    unread_count: int = 0
    last_message: MessageResponse | None = None
    updated_at: datetime
    peer_name: str | None = None    # для kind=direct: имя собеседника
    peer_phone: str | None = None   # для kind=direct: телефон собеседника

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: uuid.UUID
    kind: str
    title: str | None
    client_id: uuid.UUID | None = None
    driver_id: uuid.UUID | None = None
    order_id: uuid.UUID | None = None
    group_code: str | None = None
    created_by_id: uuid.UUID
    created_by_role: str
    participants: list[ParticipantResponse] = []
    messages: list[MessageResponse] = []
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    peer_name: str | None = None    # для kind=direct: имя собеседника
    peer_phone: str | None = None   # для kind=direct: телефон собеседника

    model_config = {"from_attributes": True}
