import uuid
from datetime import datetime
from pydantic import BaseModel, Field, AliasChoices
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
    # ORM attr is msg_metadata (metadata is reserved in SQLAlchemy Declarative).
    # validation_alias accepts both names; serialization output key is always 'metadata'.
    metadata: dict | None = Field(
        None,
        validation_alias=AliasChoices("metadata", "msg_metadata"),
    )
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
