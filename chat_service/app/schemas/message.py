import uuid
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    msg_type: Literal["text", "document"] = "text"
    metadata: dict | None = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    sender_role: str
    sender_name: str
    msg_type: str
    text: str
    metadata: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}
