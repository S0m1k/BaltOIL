import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, ForeignKey, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ConversationKind(str, enum.Enum):
    CLIENT_MANAGER      = "client_manager"       # клиент ↔ все активные менеджеры/админы
    CLIENT_DRIVER_ORDER = "client_driver_order"  # клиент ↔ водитель (на конкретный заказ)
    STAFF_GROUP         = "staff_group"           # групповой чат сотрудников
    # Прямой чат 1-на-1, начатый по номеру телефона. Приватен: видят только
    # двое участников (даже менеджер/админ не видят чужие). Членство хранится
    # в snapshot-полях client_id (инициатор) и driver_id (собеседник) — отдельные
    # колонки не заводим, чтобы избежать миграции схемы.
    DIRECT              = "direct"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Тип диалога — определяет правила доступа и членство
    kind: Mapped[str] = mapped_column(String(30), nullable=False, index=True)

    # Snapshot-поля членства (для client_manager и client_driver_order).
    # Хранятся в строке — доступ проверяется без RPC.
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    order_id:  Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Для staff_group: 'general' | 'drivers' | 'managers'
    group_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Заголовок (опциональный, иначе генерируется на фронте по kind/group_code)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(20), nullable=False)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # ConversationParticipant сохраняется только для last_read_at (счётчики непрочитанных).
    # Membership определяется snapshot-полями выше, а не этой таблицей.
    participants: Mapped[list["ConversationParticipant"]] = relationship(
        "ConversationParticipant", back_populates="conversation", cascade="all, delete-orphan"
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
    )


class ConversationParticipant(Base):
    """Хранит last_read_at для подсчёта непрочитанных.

    Не определяет членство — только для unread-счётчиков.
    Участник добавляется при первом открытии диалога (auto-enroll).
    """

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
