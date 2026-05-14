"""
Управление реквизитами юридического лица (продавца).

При каждом изменении реквизитов создаётся новая запись, старая получает
effective_to = now(). Документы хранят снимок реквизитов на момент создания,
поэтому история не ломает уже выпущенные документы.
"""
import logging
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.legal_entity import LegalEntity
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError
from app.schemas.legal_entity import LegalEntityCreate

log = logging.getLogger(__name__)

ROLE_ADMIN = "admin"


async def get_active(db: AsyncSession) -> LegalEntity | None:
    """Вернуть актуальную запись реквизитов (effective_to IS NULL)."""
    result = await db.execute(
        select(LegalEntity)
        .where(LegalEntity.effective_to.is_(None), LegalEntity.is_active.is_(True))
        .order_by(LegalEntity.effective_from.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_history(db: AsyncSession, actor: TokenUser) -> list[LegalEntity]:
    """Все версии реквизитов, от новых к старым."""
    if actor.role != ROLE_ADMIN:
        raise ForbiddenError("История реквизитов доступна только администратору")
    result = await db.execute(
        select(LegalEntity).order_by(LegalEntity.effective_from.desc())
    )
    return list(result.scalars().all())


async def create_version(
    db: AsyncSession,
    data: LegalEntityCreate,
    actor: TokenUser,
) -> LegalEntity:
    """Создать новую версию реквизитов, закрыв текущую активную запись.

    Идемпотентен: если активная запись идентична новым данным — возвращает её без изменений.
    """
    if actor.role != ROLE_ADMIN:
        raise ForbiddenError("Изменять реквизиты может только администратор")

    now = datetime.now(timezone.utc)

    # Закрываем текущую активную версию
    current = await get_active(db)
    if current is not None:
        current.effective_to = now
        current.is_active = False

    new_entity = LegalEntity(
        effective_from=now,
        **data.model_dump(),
    )
    db.add(new_entity)
    await db.flush()
    await db.refresh(new_entity)

    log.info("LegalEntity version created by admin %s: id=%s inn=%s", actor.id, new_entity.id, new_entity.inn)
    return new_entity


async def get_by_id(db: AsyncSession, entity_id, actor: TokenUser) -> LegalEntity:
    """Получить конкретную версию по ID."""
    if actor.role != ROLE_ADMIN:
        raise ForbiddenError("Доступ только для администратора")
    result = await db.execute(select(LegalEntity).where(LegalEntity.id == entity_id))
    entity = result.scalar_one_or_none()
    if not entity:
        raise NotFoundError("Запись реквизитов не найдена")
    return entity
