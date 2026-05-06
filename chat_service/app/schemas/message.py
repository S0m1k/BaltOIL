import uuid
from datetime import datetime
from pydantic import BaseModel, Field


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    sender_role: str
    sender_name: str
    text: str
    created_at: datetime

    model_config = {"from_attributes": True}
