import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.database import Base


class OrganizationFile(Base):
    """Файл организации (карточка реквизитов Word/PDF и т. п., CRM-63).

    Содержимое лежит в БД и подгружается отдельно (`deferred`): список файлов
    не тянет мегабайты, а байты читаются только при скачивании.
    """

    __tablename__ = "organization_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[bytes] = deferred(mapped_column(LargeBinary, nullable=False))
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
