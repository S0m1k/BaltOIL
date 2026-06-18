import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Text, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class ClientObject(Base):
    """Сохранённый объект доставки клиента.

    Позволяет повторно использовать адреса (например, «Склад на Невском»)
    при создании новых заявок. Привязан к client_id (== user_id клиента).
    """
    __tablename__ = "client_objects"
    __table_args__ = (
        UniqueConstraint("client_id", "delivery_address", name="uq_client_object_addr"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )

    # Необязательное название: «Склад на Невском». Если не задано, показывается адрес.
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)

    # Координаты (из DaData-геокодирования) — nullable, заполняются если известны.
    delivery_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    delivery_lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)

    # Кто создал запись (UUID пользователя)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
