import uuid
import enum
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    String, Text, Numeric, DateTime, Enum as SAEnum,
    Integer, Boolean, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class OrderStatus(str, enum.Enum):
    NEW = "new"           # Новая (создана, ждёт водителя)
    AWAITING_MANAGER = "awaiting_manager"  # На согласовании с менеджером (объём > 3000 л)
    ACCEPTED = "accepted" # Принята водителем
    DELIVERED = "delivered" # Доставлена
    CANCELLED = "cancelled" # Отменена (терминальный)


class OrderKind(str, enum.Enum):
    INDIVIDUAL = "individual"  # Физическое лицо
    COMPANY = "company"        # Юридическое лицо
    TTN_L = "ttn_l"            # Внутренняя ТТН-Л (только менеджер)


class PaymentType(str, enum.Enum):
    PREPAID = "prepaid"             # Предоплата
    ON_DELIVERY = "on_delivery"     # По факту, при прибытии
    TRADE_CREDIT = "trade_credit"   # Товарный кредит
    POSTPAID = "postpaid"           # Постоплата (по счёту)
    DEBT = "debt"                   # Условно в долг (семантически = trade_credit, разделён для отчётности)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Human-readable номер: ф1 / ю1 / л1
    order_number: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    # Вид заявки: individual / company / ttn_l
    order_kind: Mapped[OrderKind] = mapped_column(
        SAEnum(OrderKind, values_callable=lambda x: [e.value for e in x], name="orderkind"),
        nullable=False, default=OrderKind.INDIVIDUAL,
    )

    # Кто создал
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Топливо — код из каталога fuel_types (строка, напр. "diesel_summer")
    fuel_type: Mapped[str] = mapped_column(String(50), nullable=False)
    volume_requested: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)  # литры
    volume_delivered: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)  # факт

    # Доставка
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    desired_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Контактное лицо для приёмки топлива на объекте
    contact_person_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_person_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Номер ТТН — обязателен при переходе ACCEPTED→DELIVERED
    ttn_number: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Флаг подтверждения изменений водителем (выставляется при edit/reschedule ACCEPTED-заявки)
    pending_driver_ack: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Какие поля изменены с момента последнего подтверждения водителем
    # (список ключей: desired_date / volume / fuel_type / address / comment / driver / amount)
    pending_changed_fields: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Оплата
    payment_type: Mapped[PaymentType] = mapped_column(
        # values_callable ensures SQLAlchemy uses enum VALUES ('prepaid' etc.)
        # not member NAMES ('PREPAID') for the DB ↔ Python mapping.
        SAEnum(PaymentType, values_callable=lambda x: [e.value for e in x], name="paymenttype"),
        nullable=False, default=PaymentType.ON_DELIVERY
    )
    # Ожидаемая сумма (для prepaid — сумма предоплаты; для остальных — расчётная)
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Итоговая сумма после закрытия (по факту доставки)
    final_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Для trade_credit: подписан ли договор (разблокирует закрытие без оплаты)
    trade_credit_contract_signed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Статус
    status: Mapped[OrderStatus] = mapped_column(
        SAEnum(OrderStatus, values_callable=lambda x: [e.value for e in x], name="orderstatus"),
        nullable=False, default=OrderStatus.NEW, index=True,
    )

    # Организация, от имени которой создана заявка (юрлицо). NULL = «как физлицо»
    # или legacy-заявка. Soft FK на organizations.id в auth_service БД (FK не создаём).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Кто обрабатывает
    manager_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    driver_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    # Координаты адреса доставки (из DaData-геокодирования на фронте)
    delivery_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    delivery_lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # Снимок зоны на момент создания заявки (без FK на delivery_service)
    delivery_zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    delivery_zone_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Стоимость доставки, заложенная в expected_amount (NULL = уточняется менеджером)
    delivery_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Комментарии
    client_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Статус оплаты (отдельно от статуса заявки)
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unpaid", index=True
    )  # unpaid | paid | partially_paid | overpaid

    # Долговая заявка: если true — водитель доставляет без оплаты,
    # выставляется только менеджером/админом
    allow_delivery_unpaid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Мягкое удаление
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relations
    status_logs: Mapped[list["OrderStatusLog"]] = relationship(
        "OrderStatusLog", back_populates="order",
        order_by="OrderStatusLog.created_at",
        cascade="all, delete-orphan",
    )
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="order",
        order_by="Payment.created_at",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="order",
        order_by="Document.created_at",
        cascade="all, delete-orphan",
    )
