import uuid
from datetime import datetime
from pydantic import BaseModel, Field, AliasChoices
from typing import Literal


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    # photo/video/file — вложения (правки 2026-06-11 / 2026-07-11);
    # metadata: {path, mime, size, original_name}
    msg_type: Literal["text", "document", "photo", "video", "file"] = "text"
    metadata: dict | None = None
    # Ответ на сообщение (правки 2026-06-24) — id сообщения в том же диалоге.
    reply_to_id: uuid.UUID | None = None


class ReplyPreview(BaseModel):
    """Краткий снимок родительского сообщения для отрисовки «ответа» без доп. запроса."""
    id: uuid.UUID
    sender_name: str
    text: str


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    sender_role: str
    sender_name: str
    msg_type: str
    text: str
    # ORM attr is msg_metadata (metadata is reserved in SQLAlchemy Declarative).
    # msg_metadata listed first so Pydantic reads it before hitting Base.metadata.
    metadata: dict | None = Field(
        None,
        validation_alias=AliasChoices("msg_metadata", "metadata"),
    )
    created_at: datetime
    # Ответ + закреп (правки 2026-06-24)
    reply_to_id: uuid.UUID | None = None
    is_pinned: bool = False
    reply_preview: ReplyPreview | None = None
    # Статус доставки для отправителя: "sent" | "delivered" | "read".
    # Заполняется только для сообщений текущего пользователя; у чужих — None.
    status: Literal["sent", "delivered", "read"] | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}
