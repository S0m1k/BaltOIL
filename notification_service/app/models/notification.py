import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class NotificationType(str, enum.Enum):
    ORDER_CREATED  = "order_created"
    ORDER_STATUS   = "order_status"
    CHAT_MESSAGE   = "chat_message"
    TRIP_ASSIGNED  = "trip_assigned"
    TRIP_STATUS    = "trip_status"
    REPORT_READY   = "report_ready"


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Recipient
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    type: Mapped[NotificationType] = mapped_column(
        SAEnum(NotificationType), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body:  Mapped[str] = mapped_column(Text, nullable=False)

    # Cross-service reference (e.g. order_id, conv_id)
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entity_id:   Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
