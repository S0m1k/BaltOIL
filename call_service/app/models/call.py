import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime, Enum as SAEnum, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CallStatus(str, enum.Enum):
    RINGING = "ringing"   # звонок инициирован, ждём ответа
    ACTIVE  = "active"    # хотя бы один участник подключился
    ENDED   = "ended"     # завершён (после того как все вышли)
    MISSED  = "missed"    # никто не ответил, инициатор положил трубку


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # ID связанного диалога — звонки всегда привязаны к чату
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    # Имя комнаты в LiveKit — уникальный идентификатор
    room_name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    initiated_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    initiated_by_name: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[CallStatus] = mapped_column(
        SAEnum(CallStatus, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False, default=CallStatus.RINGING, index=True,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    participants: Mapped[list["CallParticipant"]] = relationship(
        "CallParticipant", back_populates="call", cascade="all, delete-orphan"
    )


class CallParticipant(Base):
    __tablename__ = "call_participants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_role: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")

    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    call: Mapped["Call"] = relationship("Call", back_populates="participants")
