import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class IdempotencyKey(Base):
    """Stores processed idempotency keys for mobile offline-outbox dedup.

    A unique constraint on `key` lets the DB prevent races: the first writer
    wins, all retries read the stored result references.
    """

    __tablename__ = "idempotency_keys"

    # Client-generated UUID string — primary key for fast lookup
    key: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Which operation this key belongs to
    operation: Mapped[str] = mapped_column(String(64), nullable=False)

    # References to the produced result (one or both may be set depending on operation)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
