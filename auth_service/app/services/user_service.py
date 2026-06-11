import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload, joinedload

from app.config import get_settings
from app.models.user import User, UserRole
from app.models.client_profile import ClientProfile, ClientType
from app.core.security import hash_password, verify_password
from app.core.phone import normalize_phone, normalized_phone_column
from app.core.exceptions import ConflictError, NotFoundError, ForbiddenError, AuthError
from app.schemas.user import (
    RegisterIndividualRequest, RegisterCompanyRequest,
    CreateUserRequest, UpdateUserRequest,
)
from app.schemas.client_profile import UpdateClientProfileRequest
from app.services.audit_service import log_action
from app.services.dadata_service import lookup_by_inn, lookup_by_bik
from app.core.token_revocation import revoke_user_tokens


# Поля, которые мы умеем подтягивать из DaData при регистрации/ресинке.
# Эти же поля используются в audit-логе для diff before/after при ресинке.
FNS_PARTY_FIELDS = (
    "company_name", "kpp", "ogrn", "legal_address",
    "okved", "okpo", "okato", "fns_status", "director_name",
)
FNS_BANK_FIELDS = ("bank_name", "correspondent_account", "swift")


def _normalize_email(email: str | None) -> str | None:
    return email.lower().strip() if email else None


async def _check_email_unique(db: AsyncSession, email: str | None, exclude_id=None) -> None:
    if not email:
        return
    q = select(User).where(User.email == email)
    if exclude_id:
        q = q.where(User.id != exclude_id)
    result = await db.execute(q)
    if result.scalar_one_or_none():
        raise ConflictError("Пользователь с таким email уже существует")


async def _check_phone_unique(db: AsyncSession, phone: str | None, exclude_id=None) -> None:
    if not phone:
        return
    # Сравниваем по нормализованному номеру (последние 10 цифр), а не по строке —
    # иначе один номер в разных форматах (+7 921…, 89219…, с пробелами/дефисами)
    # завёлся бы как разные пользователи, и логин-по-номеру нашёл бы несколько.
    norm = normalize_phone(phone)
    if len(norm) == 10:
        q = select(User).where(
            User.phone.isnot(None),
            normalized_phone_column(User.phone) == norm,
        )
    else:
        # Нестандартно короткий номер — fallback на точное сравнение.
        q = select(User).where(User.phone == phone)
    if exclude_id:
        q = q.where(User.id != exclude_id)
    result = await db.execute(q)
    if result.scalars().first():
        raise ConflictError("Пользователь с таким номером телефона уже существует")


async def register_individual(
    db: AsyncSession,
    data: RegisterIndividualRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    if data.email:
        data.email = _normalize_email(data.email)
        await _check_email_unique(db, data.email)
    await _check_phone_unique(db, data.phone)

    user = User(
        email=data.email,  # может быть None — заполнит позже в ЛК
        phone=data.phone,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.CLIENT,
    )
    db.add(user)
    await db.flush()  # get user.id before adding profile

    profile = ClientProfile(
        user_id=user.id,
        client_type=ClientType.INDIVIDUAL,
        delivery_address=data.delivery_address,
        passport_series=data.passport_series,
        passport_number=data.passport_number,
    )
    db.add(profile)
    await db.flush()

    await log_action(
        db,
        action="user.registered_individual",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": data.email},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return await get_user_by_id(db, user.id)


async def register_company(
    db: AsyncSession,
    data: RegisterCompanyRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    # email опционален (правки 2026-06-11) — клиент заполняет позже в профиле
    if data.email:
        data.email = _normalize_email(data.email)
        await _check_email_unique(db, data.email)
    await _check_phone_unique(db, data.phone)

    user = User(
        email=data.email,  # может быть None — заполнит позже в профиле
        phone=data.phone,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.CLIENT,
    )
    db.add(user)
    await db.flush()

    # DaData lookup: тянем по ИНН и БИК; то что клиент прислал руками — приоритетнее.
    api_key = get_settings().dadata_api_key
    party = await lookup_by_inn(data.inn, api_key) if api_key else None
    bank  = await lookup_by_bik(data.bik, api_key) if (api_key and data.bik) else None
    fns_sync_at = datetime.now(timezone.utc) if (party or bank) else None

    def _pick(user_val, dadata_val):
        """Ручной ввод приоритетнее; DaData только если поле пустое."""
        return user_val if (user_val not in (None, "")) else dadata_val

    party = party or {}
    bank  = bank  or {}

    profile = ClientProfile(
        user_id=user.id,
        client_type=ClientType.COMPANY,
        delivery_address=data.delivery_address,
        company_name=_pick(data.company_name, party.get("company_name")),
        inn=data.inn,
        kpp=_pick(data.kpp, party.get("kpp")),
        ogrn=party.get("ogrn"),
        legal_address=_pick(data.legal_address, party.get("legal_address")),
        bank_account=data.bank_account,
        bank_name=_pick(data.bank_name, bank.get("bank_name")),
        bik=data.bik,
        correspondent_account=_pick(data.correspondent_account, bank.get("correspondent_account")),
        # FNS-extra — только из DaData (нет полей в форме регистрации).
        okved=party.get("okved"),
        okpo=party.get("okpo"),
        okato=party.get("okato"),
        fns_status=party.get("fns_status"),
        director_name=party.get("director_name"),
        swift=bank.get("swift"),
        billing_email=data.billing_email,
        fns_last_sync_at=fns_sync_at,
    )
    db.add(profile)
    await db.flush()

    await log_action(
        db,
        action="user.registered_company",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={
            "email": data.email,
            "company": profile.company_name,
            "inn": data.inn,
            "fns_lookup_used": party != {},
            "bank_lookup_used": bank != {},
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return await get_user_by_id(db, user.id)


async def fns_resync_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    actor_id: uuid.UUID,
    ip_address: str | None = None,
) -> User:
    """Заново вызвать DaData по сохранённому ИНН/БИК и обновить поля.

    Доступ контролируется в роутере (admin/manager only). Сервис не падает,
    если DaData недоступна — просто ничего не меняет и фиксирует это в audit.
    """
    target = await get_user_by_id(db, user_id)
    profile = target.client_profile
    if profile is None or profile.client_type != ClientType.COMPANY:
        raise NotFoundError("Пользователь не является юридическим лицом")
    if not profile.inn:
        raise ConflictError("Нет сохранённого ИНН — нечего ресинкать")

    api_key = get_settings().dadata_api_key
    if not api_key:
        raise ConflictError("DaData не настроена (DADATA_API_KEY)")

    party = await lookup_by_inn(profile.inn, api_key) or {}
    bank  = await lookup_by_bik(profile.bik, api_key) if profile.bik else None
    bank  = bank or {}

    # before/after — только для полей, которые мы трогаем; пустые из DaData игнорируем
    before: dict = {}
    after:  dict = {}
    for f in FNS_PARTY_FIELDS:
        new_val = party.get(f)
        if new_val in (None, ""):
            continue
        old_val = getattr(profile, f)
        if old_val != new_val:
            before[f] = old_val
            after[f]  = new_val
            setattr(profile, f, new_val)
    for f in FNS_BANK_FIELDS:
        new_val = bank.get(f)
        if new_val in (None, ""):
            continue
        old_val = getattr(profile, f)
        if old_val != new_val:
            before[f] = old_val
            after[f]  = new_val
            setattr(profile, f, new_val)

    if party or bank:
        profile.fns_last_sync_at = datetime.now(timezone.utc)

    await db.flush()

    await log_action(
        db,
        action="user.fns_resync",
        actor_id=actor_id,
        entity_type="user",
        entity_id=target.id,
        details={
            "inn": profile.inn,
            "bik": profile.bik,
            "fns_lookup_used": party != {},
            "bank_lookup_used": bank != {},
            "before": before,
            "after": after,
        },
        ip_address=ip_address,
    )
    return await get_user_by_id(db, user_id)


async def create_user_by_admin(
    db: AsyncSession,
    data: CreateUserRequest,
    *,
    actor_id,
    ip_address: str | None = None,
) -> User:
    data.email = _normalize_email(data.email)
    await _check_email_unique(db, data.email)
    await _check_phone_unique(db, data.phone)

    user = User(
        email=data.email,
        phone=data.phone,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=data.role,
    )
    db.add(user)
    await db.flush()

    if data.role == UserRole.CLIENT:
        if not data.client_type:
            data.client_type = ClientType.INDIVIDUAL
        profile = ClientProfile(user_id=user.id, client_type=data.client_type)
        db.add(profile)

    await log_action(
        db,
        action="user.created_by_admin",
        actor_id=actor_id,
        entity_type="user",
        entity_id=user.id,
        details={"email": data.email, "role": data.role.value},
        ip_address=ip_address,
    )
    # Re-fetch with client_profile eagerly loaded to avoid lazy-load error
    return await get_user_by_id(db, user.id)


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User)
        .options(selectinload(User.client_profile))
        .where(User.id == user_id, User.is_archived == False)  # noqa: E712
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Пользователь не найден")
    return user


async def list_users(
    db: AsyncSession,
    *,
    role: UserRole | None = None,
    exclude_role: UserRole | None = None,
    include_inactive: bool = False,
    offset: int = 0,
    limit: int = 50,
    client_number: int | None = None,
) -> list[User]:
    conditions = [User.is_archived == False]  # noqa: E712
    if role:
        conditions.append(User.role == role)
    if exclude_role:
        # Исключаем роль на уровне SQL (а не в Python после LIMIT) — иначе LIMIT
        # мог отрезать staff, оставив страницу из клиентов, которых потом отфильтровали.
        conditions.append(User.role != exclude_role)
    if not include_inactive:
        conditions.append(User.is_active == True)  # noqa: E712

    query = (
        select(User)
        .where(and_(*conditions))
        .options(joinedload(User.client_profile))
        .order_by(User.full_name)  # детерминированный порядок для LIMIT
    )

    if client_number is not None:
        query = query.join(ClientProfile, ClientProfile.user_id == User.id).where(
            ClientProfile.client_number == client_number
        )

    result = await db.execute(query.offset(offset).limit(limit))
    return list(result.scalars().all())


async def update_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: UpdateUserRequest,
    *,
    actor: User,
    ip_address: str | None = None,
) -> User:
    user = await get_user_by_id(db, user_id)

    # Чужой профиль редактируют только admin/manager (напр. паспорт водителя); остальные — только свой
    if actor.role not in (UserRole.ADMIN, UserRole.MANAGER) and actor.id != user_id:
        raise ForbiddenError("Редактирование чужого профиля запрещено")

    # Только admin меняет роли и активность
    if data.role is not None and actor.role != UserRole.ADMIN:
        raise ForbiddenError("Изменение роли доступно только администратору")
    if data.is_active is not None and actor.role != UserRole.ADMIN:
        raise ForbiddenError("Изменение активности доступно только администратору")

    changed = {}
    # email: use model_fields_set to distinguish "not sent" from "explicitly set to null".
    # Admin can clear email for individuals by sending {"email": null}.
    if "email" in data.model_fields_set:
        new_email = _normalize_email(data.email) if data.email else None
        if new_email != user.email:
            if new_email:
                await _check_email_unique(db, new_email, exclude_id=user_id)
            changed["email"] = {"old": user.email, "new": new_email}
            user.email = new_email
    elif data.email and data.email != user.email:
        # Backwards-compat: if using the old pattern (email present, non-null)
        await _check_email_unique(db, data.email, exclude_id=user_id)
        changed["email"] = {"old": user.email, "new": data.email}
        user.email = data.email
    if data.phone is not None:
        user.phone = data.phone
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.is_active is not None:
        changed["is_active"] = {"old": user.is_active, "new": data.is_active}
        user.is_active = data.is_active
    if data.role is not None:
        changed["role"] = {"old": user.role.value, "new": data.role.value}
        user.role = data.role
    # Паспортные данные (водитель) — для доверенности М-2. Вносит только
    # менеджер/админ: иначе клиент мог бы подсунуть произвольный паспорт в юр-документ.
    if actor.role in (UserRole.ADMIN, UserRole.MANAGER):
        if data.passport_series is not None:
            user.passport_series = data.passport_series or None
        if data.passport_number is not None:
            user.passport_number = data.passport_number or None
        if data.passport_issued_by is not None:
            user.passport_issued_by = data.passport_issued_by or None
        if data.passport_issued_at is not None:
            user.passport_issued_at = data.passport_issued_at

    # Деактивация или смена роли должны немедленно отрезать активные access-токены
    # (прочие сервисы не перечитывают User из БД).
    if data.is_active is False or "role" in changed:
        await revoke_user_tokens(str(user_id))

    if changed:
        await log_action(
            db,
            action="user.updated",
            actor_id=actor.id,
            entity_type="user",
            entity_id=user_id,
            details=changed,
            ip_address=ip_address,
        )
    return user


async def archive_user(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    actor: User,
    ip_address: str | None = None,
) -> User:
    user = await get_user_by_id(db, user_id)

    if user.id == actor.id:
        raise ForbiddenError("Нельзя архивировать самого себя")

    user.is_archived = True
    user.archived_at = datetime.now(timezone.utc)
    user.is_active = False

    # Немедленно отозвать активные access-токены архивируемого: прочие сервисы
    # не перечитывают User из БД, иначе токен жил бы до естественного истечения.
    await revoke_user_tokens(str(user_id))

    await log_action(
        db,
        action="user.archived",
        actor_id=actor.id,
        entity_type="user",
        entity_id=user_id,
        ip_address=ip_address,
    )
    return user


async def change_password(
    db: AsyncSession,
    *,
    actor: User,
    current_password: str,
    new_password: str,
    ip_address: str | None = None,
) -> None:
    """User changes their own password. Revokes all existing refresh tokens."""
    if not verify_password(current_password, actor.hashed_password):
        raise AuthError("Неверный текущий пароль")

    actor.hashed_password = hash_password(new_password)

    # Revoke all refresh tokens to force re-login on all devices
    from app.models.refresh_token import RefreshToken
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == actor.id,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
    )
    for token in result.scalars().all():
        token.is_revoked = True

    await revoke_user_tokens(str(actor.id))

    await log_action(
        db,
        action="user.password_changed",
        actor_id=actor.id,
        entity_type="user",
        entity_id=actor.id,
        ip_address=ip_address,
    )


async def update_client_profile(
    db: AsyncSession,
    user_id: uuid.UUID,
    data: UpdateClientProfileRequest,
    *,
    actor: User,
    ip_address: str | None = None,
) -> ClientProfile:
    # Only the client themselves, or admin / manager — driver role is not allowed
    if actor.role == UserRole.DRIVER:
        raise ForbiddenError("Водитель не может редактировать профиль клиента")
    if actor.role == UserRole.CLIENT and actor.id != user_id:
        raise ForbiddenError()

    result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("Профиль клиента не найден")

    changed = {}
    # exclude_unset (а не exclude_none): пропущенные поля не трогаем, но явно
    # переданный null МОЖЕТ сбросить значение (tariff_id=null → default-тариф,
    # credit_limit=null → лимита нет). С exclude_none сброс в NULL был невозможен.
    for field, value in data.model_dump(exclude_unset=True).items():
        old = getattr(profile, field)
        if old != value:
            changed[field] = {"old": str(old) if old is not None else None, "new": str(value)}
            setattr(profile, field, value)

    if changed:
        await log_action(
            db,
            action="client_profile.updated",
            actor_id=actor.id,
            entity_type="client_profile",
            entity_id=user_id,
            details=changed,
            ip_address=ip_address,
        )

    return profile


async def update_client_tariff(
    db: AsyncSession,
    user_id: uuid.UUID,
    data,
    *,
    actor: User,
) -> ClientProfile:
    """Назначение тарифа, credit_allowed и коэффициентов клиенту — только admin."""
    if actor.role != UserRole.ADMIN:
        raise ForbiddenError("Только администратор может менять тарифы")

    result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("Профиль клиента не найден")

    # exclude_unset: позволяет сбросить tariff_id/credit_limit в NULL явным null,
    # не затрагивая пропущенные поля.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    return profile
