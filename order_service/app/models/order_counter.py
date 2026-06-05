"""Atomic per-kind order number counter backed by a DB row with upsert."""
from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class OrderKindCounter(Base):
    """Счётчик номеров заявок по виду (individual/company/ttn_l).

    Ключ = kind value ('individual', 'company', 'ttn_l').
    Инкрементируется через INSERT ... ON CONFLICT DO UPDATE RETURNING — атомарно.
    """
    __tablename__ = "order_kind_counters"

    kind: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
