import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Enum as SAEnum, ForeignKey, func, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ConversationType(str, enum.Enum):
    CLIENT_SUPPORT = "client_support"  # клиент ↔ менеджер/админ (привязан к заявке)
    INTERNAL       = "internal"        # внутренний: менеджер/админ/водитель


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # Уникальность по набору участников: один чат на один состав
        UniqueConstraint("participants_hash", name="uq_conversation_participants_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    type: Mapped[ConversationType] = mapped_column(SAEnum(ConversationType), nullable=False, index=True)

    # Хэш (sha256) от отсортированных UUID участников — для upsert-дедупликации
    participants_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Заголовок
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    participants: Mapped[list["ConversationParticipant"]] = relationship(
        "ConversationParticipant", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
    )


class ConversationParticipant(Base):
    """Участник диалога с меткой последнего прочитанного сообщения."""

    __tablename__ = "conversation_participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_role: Mapped[str] = mapped_column(String(20), nullable=False)
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="participants")
