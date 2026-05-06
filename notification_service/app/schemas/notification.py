import uuid
from datetime import datetime
from pydantic import BaseModel
from app.models.notification import NotificationType


class NotificationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PublishRequest(BaseModel):
    """Internal endpoint — called by other services to create notifications."""
    user_ids: list[uuid.UUID]        # recipients
    type: NotificationType
    title: str
    body: str
    entity_type: str | None = None
    entity_id: uuid.UUID | None = None
