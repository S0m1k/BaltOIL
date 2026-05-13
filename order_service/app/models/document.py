import uuid
import enum
from datetime import datetime
from sqlalchemy import String, Text, DateTime, Enum as SAEnum, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class DocumentType(str, enum.Enum):
    INVOICE = "invoice"     # Счёт на оплату
    UPD = "upd"             # УПД (универсальный передаточный документ)
    TTN = "ttn"             # ТТН (товарно-транспортная накладная)


class DocumentStatus(str, enum.Enum):
    DRAFT = "draft"         # Черновик (генерируется)
    READY = "ready"         # Готов (PDF создан)
    SENT = "sent"           # Отправлен клиенту через чат
    CANCELLED = "cancelled" # Аннулирован


class Document(Base):
    """Документ (счёт, УПД, ТТН), привязанный к заявке.

    seller_snapshot и buyer_snapshot содержат снимок реквизитов на момент
    генерации — так документ остаётся корректным даже если реквизиты изменились.
    """
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    doc_type: Mapped[DocumentType] = mapped_column(SAEnum(DocumentType), nullable=False)
    doc_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus), nullable=False, default=DocumentStatus.DRAFT
    )

    # Снимки реквизитов на момент генерации
    seller_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    buyer_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Данные документа
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_amount: Mapped[float | None] = mapped_column(nullable=True)
    volume: Mapped[float | None] = mapped_column(nullable=True)  # литры

    # Файл PDF (путь или S3 ключ)
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Кто создал
    created_by_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    order: Mapped["Order"] = relationship("Order", back_populates="documents")
