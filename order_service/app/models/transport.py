"""Перевозка (ТЗ Ирины, 09.2026): справочники + детали заявки на перевозку.

Справочники живут в order_service, а не в auth_service, намеренно:

* «Нефтебазы» — чистый справочник точек маршрута со стоимостью доставки по
  умолчанию, к пользователям и организациям заявок отношения не имеет;
* «Объекты клиентов» — организация-объект с несколькими адресами и
  прикреплённым договором-файлом. Переиспользовать ``organizations``
  auth_service было бы дороже и опаснее: там членство, реквизиты, счета и
  договоры заявок — любая правка задевает существующий поток заявок.
  ТЗ прямо допускает отдельные сущности, поэтому берём их.

Детали самой перевозки вынесены в отдельную таблицу 1:1 к ``orders``
(``transport_details``): заявка на перевозку — это Order с
``order_kind='transport'``, чтобы бесплатно получить общий список, статусы,
ТТН, журнал действий и чат. Двадцать «перевозочных» колонок в таблице orders,
пустых у всех остальных заявок, класть не стали.
"""
import uuid
import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    String, Text, Numeric, DateTime, Integer, Boolean, ForeignKey, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TransportType(str, enum.Enum):
    """Тип перевозки (блок 1 формы)."""

    TO_BASE = "to_base"      # доставка на базу
    TO_CLIENT = "to_client"  # услуга доставки клиенту


class RoutePointKind(str, enum.Enum):
    """Вид точки маршрута. Хранится рядом с id/текстом точки.

    ``base`` — собственная база СЗТК («куда» по умолчанию для доставки на базу),
    отдельной записи в справочнике не имеет, поэтому point_id у неё пуст.
    """

    OIL_DEPOT = "oil_depot"          # нефтебаза из справочника
    BASE = "base"                    # наша база
    CLIENT_OBJECT = "client_object"  # объект клиента из справочника


class TransportBase(Base):
    """Нефтебаза: название + стоимость доставки по умолчанию.

    Реквизиты нефтебазы по ТЗ откладываются — колонок под них не заводим,
    чтобы не плодить мёртвую схему.
    """

    __tablename__ = "transport_bases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Стоимость доставки по умолчанию, руб. NULL = не задана.
    default_delivery_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TransportClientObject(Base):
    """Объект клиента: организация-объект с договором-файлом и адресами."""

    __tablename__ = "transport_client_objects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Прикреплённый клиент (user_id в auth_service). Soft FK — межсервисный.
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    # Договор — просто загруженный файл (отдельная форма договора по ТЗ — потом).
    # Путь относительно MEDIA_ROOT, имя — как у пользователя при загрузке.
    contract_file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract_file_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    addresses: Mapped[list["TransportClientAddress"]] = relationship(
        "TransportClientAddress",
        back_populates="client_object",
        order_by="TransportClientAddress.sort_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class TransportClientAddress(Base):
    """Один из адресов объекта клиента (их может быть несколько)."""

    __tablename__ = "transport_client_addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    object_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("transport_client_objects.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    address: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    client_object: Mapped["TransportClientObject"] = relationship(
        "TransportClientObject", back_populates="addresses"
    )


class TransportDetail(Base):
    """Детали заявки на перевозку — 1:1 к orders (order_kind='transport').

    Блок 1 (маршрут, количество, дата, тип) виден водителю.
    Блок 2 (цены, плотность, оплаты поставщику и водителю) — только staff;
    сервис отдаёт его исключительно менеджеру и администратору.
    """

    __tablename__ = "transport_details"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # ── Блок 1 ────────────────────────────────────────────────────────────
    transport_type: Mapped[str] = mapped_column(String(20), nullable=False)

    # Клиент, выбранный для «услуги доставки клиенту» (из объектов клиентов).
    client_object_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    route_from_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    route_from_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    route_from_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    route_to_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    route_to_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    route_to_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # До 3 промежуточных точек: [{"kind": ..., "id": ..., "text": ...}]
    waypoints: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    amount_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)
    amount_l: Mapped[Decimal | None] = mapped_column(Numeric(14, 3), nullable=True)

    # Желаемая дата доставки — свободный текст, без календаря (ТЗ).
    desired_date_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Блок 2: «куплено» (тип «доставка на базу») ────────────────────────
    price_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    price_per_l: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    density: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)

    # 4 пары «сумма + дата»: [{"amount": "1000.00", "date": "2026-09-10"}]
    supplier_payments: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # ── Блок 2: «оплаты» (тип «услуга доставки клиенту») ──────────────────
    delivery_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    delivery_paid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # ── Оплата водителю (оба типа) ───────────────────────────────────────
    driver_payment_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    driver_payment_percent: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
