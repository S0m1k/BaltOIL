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

    # Снимаем «до» для audit log
    current = await get_active(db)
    before_data: dict | None = None
    if current is not None:
        before_data = {
            "id": str(current.id),
            "name": current.name,
            "inn": current.inn,
            "kpp": current.kpp,
            "phone": current.phone,
            "email": current.email,
            "director_name": current.director_name,
        }
        current.effective_to = now
        current.is_active = False

    new_entity = LegalEntity(
        effective_from=now,
        created_by_id=actor.id,
        **data.model_dump(),
    )
    db.add(new_entity)
    await db.flush()
    await db.refresh(new_entity)

    after_data = {
        "id": str(new_entity.id),
        "name": new_entity.name,
        "inn": new_entity.inn,
        "kpp": new_entity.kpp,
        "phone": new_entity.phone,
        "email": new_entity.email,
        "director_name": new_entity.director_name,
    }

    log.info(
        "audit action=legal_entity.updated actor_id=%s before=%s after=%s",
        actor.id, before_data, after_data,
    )
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


async def get_seller_snapshot(db: AsyncSession) -> dict | None:
    """Получить активные реквизиты продавца как плоский dict для хранения в JSONB-снимке.

    Возвращает None если реквизиты ещё не заданы.
    """
    entity = await get_active(db)
    if entity is None:
        return None
    return {
        "name": entity.name,
        "short_name": entity.short_name,
        "inn": entity.inn,
        "kpp": entity.kpp,
        "ogrn": entity.ogrn,
        "okpo": entity.okpo,
        "bank_name": entity.bank_name,
        "bik": entity.bik,
        "checking_account": entity.checking_account,
        "correspondent_account": entity.correspondent_account,
        "legal_address": entity.legal_address,
        "actual_address": entity.actual_address,
        "phone": entity.phone,
        "email": entity.email,
        "director_name": entity.director_name,
        "director_title": entity.director_title,
        "vat_rate": entity.vat_rate,
    }
