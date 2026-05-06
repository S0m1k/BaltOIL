import uuid
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from sqlalchemy.orm import selectinload

from app.models.user import User, UserRole
from app.models.client_profile import ClientProfile, ClientType
from app.core.security import hash_password, verify_password
from app.core.exceptions import ConflictError, NotFoundError, ForbiddenError, AuthError
from app.schemas.user import (
    RegisterIndividualRequest, RegisterCompanyRequest,
    CreateUserRequest, UpdateUserRequest,
)
from app.schemas.client_profile import UpdateClientProfileRequest
from app.services.audit_service import log_action


def _normalize_email(email: str) -> str:
    return email.lower().strip()


async def _check_email_unique(db: AsyncSession, email: str, exclude_id=None) -> None:
    q = select(User).where(User.email == email)
    if exclude_id:
        q = q.where(User.id != exclude_id)
    result = await db.execute(q)
    if result.scalar_one_or_none():
        raise ConflictError("Пользователь с таким email уже существует")


async def register_individual(
    db: AsyncSession,
    data: RegisterIndividualRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    data.email = _normalize_email(data.email)
    await _check_email_unique(db, data.email)

    user = User(
        email=data.email,
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
    data.email = _normalize_email(data.email)
    await _check_email_unique(db, data.email)

    user = User(
        email=data.email,
        phone=data.phone,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        role=UserRole.CLIENT,
    )
    db.add(user)
    await db.flush()

    profile = ClientProfile(
        user_id=user.id,
        client_type=ClientType.COMPANY,
        delivery_address=data.delivery_address,
        company_name=data.company_name,
        inn=data.inn,
        kpp=data.kpp,
        legal_address=data.legal_address,
        bank_account=data.bank_account,
        bank_name=data.bank_name,
        bik=data.bik,
        correspondent_account=data.correspondent_account,
    )
    db.add(profile)
    await db.flush()

    await log_action(
        db,
        action="user.registered_company",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"email": data.email, "company": data.company_name, "inn": data.inn},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return await get_user_by_id(db, user.id)


async def create_user_by_admin(
    db: AsyncSession,
    data: CreateUserRequest,
    *,
    actor_id,
    ip_address: str | None = None,
) -> User:
    data.email = _normalize_email(data.email)
    await _check_email_unique(db, data.email)

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
    include_inactive: bool = False,
    offset: int = 0,
    limit: int = 50,
) -> list[User]:
    conditions = [User.is_archived == False]  # noqa: E712
    if role:
        conditions.append(User.role == role)
    if not include_inactive:
        conditions.append(User.is_active == True)  # noqa: E712

    result = await db.execute(
        select(User).where(and_(*conditions)).offset(offset).limit(limit)
    )
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

    # Only admin can change roles or deactivate others
    if data.role is not None and actor.role != UserRole.ADMIN:
        raise ForbiddenError("Изменение роли доступно только администратору")

    changed = {}
    if data.email and data.email != user.email:
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
) -> ClientProfile:
    # Only the client themselves or admin/manager
    if actor.role == UserRole.CLIENT and actor.id != user_id:
        raise ForbiddenError()

    result = await db.execute(
        select(ClientProfile).where(ClientProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise NotFoundError("Профиль клиента не найден")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    return profile
