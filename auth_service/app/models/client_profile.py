import uuid
import enum
from datetime import datetime
from decimal import Decimal
import sqlalchemy as sa
from sqlalchemy import String, ForeignKey, DateTime, Enum as SAEnum, func, Text, Numeric, Integer
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
    client_type: Mapped[ClientType] = mapped_column(
        SAEnum(ClientType, values_callable=lambda x: [e.value for e in x], name="clienttype"),
        nullable=False,
    )

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
    ogrn: Mapped[str | None] = mapped_column(String(15), nullable=True)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bik: Mapped[str | None] = mapped_column(String(9), nullable=True)
    correspondent_account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credit_allowed: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Расширенные реквизиты из DaData (ФНС / банковский справочник).
    # Заполняются при регистрации и при ресинке POST /users/{id}/fns-resync.
    okved: Mapped[str | None] = mapped_column(String(20), nullable=True)
    okpo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    okato: Mapped[str | None] = mapped_column(String(11), nullable=True)
    # ACTIVE / LIQUIDATING / LIQUIDATED / REORGANIZING — из DaData state.status.
    fns_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    swift: Mapped[str | None] = mapped_column(String(11), nullable=True)

    # Отдельный email для документов и уведомлений (если не задан — используем User.email).
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Когда последний раз дёргали DaData — null если данных нет/сервис был недоступен.
    fns_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Ссылка на тариф в order_service БД (soft FK — разные БД, FK не создаётся).
    # NULL означает «использовать default-тариф» — order_service делает fallback сам.
    tariff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Кредитный лимит: максимальная сумма, на которую клиент может закрыть заявку в долг.
    # NULL = лимита нет (требуется оплата или одобрение менеджера).
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Короткий номер клиента (C-00042). Автоприсваивается через SEQUENCE при создании.
    # server_default нужен, чтобы SQLAlchemy не подставлял NULL явно в INSERT
    # (миграция 0004 кладёт DEFAULT nextval, ORM должен знать про него).
    client_number: Mapped[int] = mapped_column(
        Integer, unique=True, index=True, nullable=False,
        server_default=sa.text("nextval('client_number_seq')"),
    )

    # Устаревшие коэффициенты — оставлены для возможного отката; не используются в новой логике.
    # Удалить после стабилизации тарифной системы на проде (≥ 1 недели).
    fuel_coefficient: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=1.0)
    delivery_coefficient: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=1.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    user: Mapped["User"] = relationship("User", back_populates="client_profile")
