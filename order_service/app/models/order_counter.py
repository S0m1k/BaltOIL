"""Atomic per-year order number counter backed by a DB row with upsert."""
from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class OrderYearCounter(Base):
    __tablename__ = "order_year_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
