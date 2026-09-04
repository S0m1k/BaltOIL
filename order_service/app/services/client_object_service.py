import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError

from app.models.client_object import ClientObject
from app.schemas.client_object import ClientObjectCreateRequest
from app.core.dependencies import TokenUser
from app.core.exceptions import ForbiddenError, ValidationError, NotFoundError

log = logging.getLogger(__name__)

ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"
ROLE_CLIENT = "client"

_CAP = 15  # Максимум сохранённых объектов на клиента


def _is_staff(actor: TokenUser) -> bool:
    return actor.role in (ROLE_MANAGER, ROLE_ADMIN)


def _resolve_owner(data: ClientObjectCreateRequest, actor: TokenUser) -> uuid.UUID:
    """Вернуть client_id владельца объекта с проверкой прав."""
    if _is_staff(actor):
        return data.client_id or actor.id
    # Клиент не может указывать чужой client_id
    if data.client_id and data.client_id != actor.id:
        raise ForbiddenError("Клиент не может создавать объекты для других клиентов")
    return actor.id


async def list_objects(
    db: AsyncSession,
    actor: TokenUser,
    client_id: uuid.UUID | None,
    organization_id: uuid.UUID | None = None,
) -> list[ClientObject]:
    """Вернуть список сохранённых объектов.

    Клиент: всегда свои. Staff: по переданному client_id.
    CRM-45: если передана организация — её объекты видны в дополнение к объектам
    клиента (заявку на организацию мог оформлять другой человек, а адрес и
    контакт приёмки у объекта общие).
    """
    target = actor.id if not _is_staff(actor) else client_id
    if target is None and organization_id is None:
        return []

    conditions = []
    if target is not None:
        conditions.append(ClientObject.client_id == target)
    if organization_id is not None:
        conditions.append(ClientObject.organization_id == organization_id)

    result = await db.execute(
        select(ClientObject)
        .where(or_(*conditions))
        .order_by(ClientObject.updated_at.desc())
    )
    return list(result.scalars().all())


async def remember_from_order(db: AsyncSession, order, actor: TokenUser) -> None:
    """CRM-45: запомнить адрес и контакт приёмки заявки в объектах клиента.

    Вызывается при создании и правке заявки. Ключ — (клиент, адрес): повторная
    заявка на тот же адрес обновляет контакт и организацию, а не плодит записи.
    Best-effort: журнал адресов не стоит того, чтобы из-за него падало
    сохранение заявки, поэтому любые ошибки только логируются.

    Коммита нет — запись уезжает вместе с транзакцией заявки.
    """
    address = (order.delivery_address or "").strip()
    if not address:
        return
    try:
        # Savepoint: конфликт уникальности (client_id, address) в гонке откатит
        # только эту вставку, а не всю транзакцию заявки.
        async with db.begin_nested():
            await _upsert_object(db, order, actor)
    except Exception as exc:
        log.warning(
            "remember_from_order: объект доставки не сохранён (не критично): %s", exc
        )


async def _upsert_object(db: AsyncSession, order, actor: TokenUser) -> None:
    address = order.delivery_address.strip()
    existing = await db.execute(
        select(ClientObject).where(
            ClientObject.client_id == order.client_id,
            ClientObject.delivery_address == address,
        )
    )
    obj = existing.scalar_one_or_none()

    if obj is None:
        count_result = await db.execute(
            select(func.count()).where(ClientObject.client_id == order.client_id)
        )
        if count_result.scalar_one() >= _CAP:
            # Лимит: молча не сохраняем — клиент почистит список сам.
            return
        obj = ClientObject(
            client_id=order.client_id,
            delivery_address=address,
            created_by_id=actor.id,
        )
        db.add(obj)

    if order.organization_id is not None:
        obj.organization_id = order.organization_id
    if order.delivery_lat is not None and order.delivery_lon is not None:
        obj.delivery_lat = order.delivery_lat
        obj.delivery_lon = order.delivery_lon
    # Пустой контакт в заявке ранее сохранённый не затирает: заявку могли
    # оформить «со слов», а справочник уже знает, кто принимает на объекте.
    if order.contact_person_name:
        obj.contact_person_name = order.contact_person_name
    if order.contact_person_phone:
        obj.contact_person_phone = order.contact_person_phone

    await db.flush()


async def create_object(
    db: AsyncSession,
    data: ClientObjectCreateRequest,
    actor: TokenUser,
) -> ClientObject:
    """Создать или обновить сохранённый объект (upsert по адресу)."""
    owner_id = _resolve_owner(data, actor)
    address = data.delivery_address  # уже stripped валидатором

    # Upsert: ищем существующую запись с тем же адресом
    existing = await db.execute(
        select(ClientObject).where(
            ClientObject.client_id == owner_id,
            ClientObject.delivery_address == address,
        )
    )
    obj = existing.scalar_one_or_none()

    if obj is not None:
        # Обновляем метаданные, не считается против лимита
        if data.name is not None:
            obj.name = data.name
        if data.delivery_lat is not None:
            obj.delivery_lat = data.delivery_lat
        if data.delivery_lon is not None:
            obj.delivery_lon = data.delivery_lon
        await db.commit()
        await db.refresh(obj)
        return obj

    # Проверяем лимит перед созданием новой записи
    count_result = await db.execute(
        select(func.count()).where(ClientObject.client_id == owner_id)
    )
    count = count_result.scalar_one()
    if count >= _CAP:
        raise ValidationError(
            f"Достигнут лимит {_CAP} сохранённых объектов — удалите лишние"
        )

    obj = ClientObject(
        client_id=owner_id,
        delivery_address=address,
        name=data.name,
        delivery_lat=data.delivery_lat,
        delivery_lon=data.delivery_lon,
        created_by_id=actor.id,
    )
    db.add(obj)
    try:
        await db.commit()
    except IntegrityError:
        # Гонка: параллельный запрос уже вставил тот же (client_id, address).
        # Дедуп вместо 500 — перечитываем существующую запись и обновляем метаданные.
        await db.rollback()
        existing = await db.execute(
            select(ClientObject).where(
                ClientObject.client_id == owner_id,
                ClientObject.delivery_address == address,
            )
        )
        obj = existing.scalar_one()
        if data.name is not None:
            obj.name = data.name
        if data.delivery_lat is not None:
            obj.delivery_lat = data.delivery_lat
        if data.delivery_lon is not None:
            obj.delivery_lon = data.delivery_lon
        await db.commit()
        await db.refresh(obj)
        return obj
    await db.refresh(obj)
    log.info("client_object.created object_id=%s client_id=%s actor=%s", obj.id, owner_id, actor.id)
    return obj


async def delete_object(
    db: AsyncSession,
    object_id: uuid.UUID,
    actor: TokenUser,
) -> None:
    """Удалить сохранённый объект. Клиент может удалять только свои."""
    result = await db.execute(
        select(ClientObject).where(ClientObject.id == object_id)
    )
    obj = result.scalar_one_or_none()

    if obj is None:
        raise NotFoundError("Объект не найден")

    # Клиент видит только свои объекты — возвращаем 404 чтобы не раскрывать чужие id
    if not _is_staff(actor) and obj.client_id != actor.id:
        raise NotFoundError("Объект не найден")

    await db.delete(obj)
    await db.commit()
    log.info("client_object.deleted object_id=%s actor=%s", object_id, actor.id)
