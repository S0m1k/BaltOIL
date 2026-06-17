import uuid
import enum
from datetime import datetime
from decimal import Decimal
import sqlalchemy as sa
from sqlalchemy import String, ForeignKey, DateTime, Enum as SAEnum, func, Text, Numeric, Integer, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class MemberRole(str, enum.Enum):
    OWNER = "owner"    # правит реквизиты и управляет составом
    MEMBER = "member"  # создаёт заявки от организации, видит её документы


class MemberStatus(str, enum.Enum):
    ACTIVE = "active"    # привязан к существующему аккаунту
    PENDING = "pending"  # приглашён по телефону, аккаунта ещё нет


class Organization(Base):
    """Организация (юрлицо), от имени которой клиент делает заявки.

    Один человек может состоять в нескольких организациях, а в одной
    организации — несколько сотрудников (см. OrganizationMember, m2m).
    Реквизиты и коммерческие условия (тариф/кредит) — на уровне организации.
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # Короткий номер организации (O-00042) — по аналогии с client_number.
    org_number: Mapped[int] = mapped_column(
        Integer, unique=True, index=True, nullable=False,
        server_default=sa.text("nextval('org_number_seq')"),
    )

    # Реквизиты
    company_name: Mapped[str] = mapped_column(String(500), nullable=False)
    inn: Mapped[str | None] = mapped_column(String(12), nullable=True, index=True)
    kpp: Mapped[str | None] = mapped_column(String(9), nullable=True)
    ogrn: Mapped[str | None] = mapped_column(String(15), nullable=True)
    legal_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bik: Mapped[str | None] = mapped_column(String(9), nullable=True)
    bank_account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    correspondent_account: Mapped[str | None] = mapped_column(String(20), nullable=True)
    swift: Mapped[str | None] = mapped_column(String(11), nullable=True)

    contract_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # DaData (ЕГРЮЛ/ЕГРИП)
    okved: Mapped[str | None] = mapped_column(String(20), nullable=True)
    okpo: Mapped[str | None] = mapped_column(String(10), nullable=True)
    okato: Mapped[str | None] = mapped_column(String(11), nullable=True)
    fns_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fns_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Коммерческие условия (soft FK на tariffs.id в order_service БД)
    tariff_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    credit_allowed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    fuel_coefficient: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=1.0)
    delivery_coefficient: Mapped[float] = mapped_column(Numeric(5, 3), nullable=False, default=1.0)

    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    members: Mapped[list["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMember(Base):
    """Членство пользователя в организации (m2m с ролью).

    Для приглашения по телефону до регистрации: user_id = NULL,
    invite_phone заполнен, status = pending. При регистрации auth_service
    привязывает приглашение к новому пользователю.
    """

    __tablename__ = "organization_members"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # NULL пока приглашение pending (аккаунта ещё нет)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    # Нормализованный телефон приглашения (последние цифры) — для pending
    invite_phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    member_role: Mapped[MemberRole] = mapped_column(
        SAEnum(MemberRole, values_callable=lambda x: [e.value for e in x], name="memberrole"),
        nullable=False, default=MemberRole.MEMBER,
    )
    status: Mapped[MemberStatus] = mapped_column(
        SAEnum(MemberStatus, values_callable=lambda x: [e.value for e in x], name="memberstatus"),
        nullable=False, default=MemberStatus.ACTIVE,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="members")
