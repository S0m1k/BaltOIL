import uuid
import enum
from datetime import datetime, date
from sqlalchemy import String, Text, DateTime, Date, Integer, Enum as SAEnum, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ContractStatus(str, enum.Enum):
    ACTIVE = "active"          # Действующий
    TERMINATED = "terminated"  # Расторгнут
    EXPIRED = "expired"        # Истёк срок действия


class Contract(Base):
    """Договор поставки нефтепродуктов между продавцом и клиентом.

    Живёт на клиенте (не на заявке): один активный договор на пару
    (продавец, клиент). seller_snapshot/buyer_snapshot — снимки реквизитов
    на момент заключения, чтобы изменение реквизитов не ломало уже
    выпущенный договор (та же модель, что и в documents).
    """
    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # UUID пользователя-клиента из auth_service (soft FK — разные БД).
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Номер вида "034/02" (seq/месяц).
    contract_number: Mapped[str] = mapped_column(
        String(20), nullable=False, unique=True, index=True
    )

    seller_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    buyer_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    signed_at: Mapped[date | None] = mapped_column(Date, nullable=True)        # дата заключения
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)  # +5 лет по образцу

    status: Mapped[ContractStatus] = mapped_column(
        SAEnum(ContractStatus, values_callable=lambda x: [e.value for e in x], name="contractstatus"),
        nullable=False, default=ContractStatus.ACTIVE,
    )

    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ContractMonthCounter(Base):
    """Атомарный счётчик номеров договоров по месяцам.

    Ключ = "YYYY-MM", last_seq инкрементится через INSERT ... ON CONFLICT
    DO UPDATE (та же схема, что OrderYearCounter) — без гонок.
    """
    __tablename__ = "contract_month_counters"

    month_key: Mapped[str] = mapped_column(String(7), primary_key=True)  # "2026-02"
    last_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
