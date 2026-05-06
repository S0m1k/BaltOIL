import uuid
import enum
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Enum as SAEnum, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class ClientType(str, enum.Enum):
    INDIVIDUAL = "individual"  # Физическое лицо
    COMPANY = "company"        # Юридическое лицо


class ClientProfile(Base):
    __tablename__ = "client_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    client_type: Mapped[ClientType] = mapped_column(SAEnum(ClientType), nullable=False)

    # Common fields
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Individual-only fields
    passport_series: Mapped[str | None] = mapped_column(String(10), nullable=True)
    passport_number: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Company-only fields
    company_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    inn: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    kpp: Mapped[str | None] = mapped_column(String(9), nullable=True)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bik: Mapped[str | None] = mapped_column(String(9), nullable=True)
    correspondent_account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credit_allowed: Mapped[bool] = mapped_column(default=False, nullable=False)  # товарный кредит

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    user: Mapped["User"] = relationship("User", back_populates="client_profile")
