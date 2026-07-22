"""Бизнес-логика организаций и членства (m2m).

Организация — юрлицо, от имени которого клиент делает заявки. Один человек
может состоять в нескольких организациях; в одной организации — несколько
сотрудников. Реквизиты и коммерческие условия — на уровне организации.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import NotFoundError, ForbiddenError, ConflictError
from app.core.phone import normalize_phone, normalized_phone_column
from app.models.user import User, UserRole
from app.models.organization import (
    Organization, OrganizationMember, MemberRole, MemberStatus,
)
from app.schemas.organization import (
    CreateOrganizationRequest, UpdateOrganizationRequest,
    UpdateOrganizationCommercialRequest,
)
from app.services.dadata_service import lookup_by_inn, lookup_by_bik

_STAFF_ROLES = (UserRole.ADMIN, UserRole.MANAGER)


def _pick(manual, dadata):
    """Приоритет ручного ввода над DaData."""
    return manual if manual not in (None, "") else dadata


# ─────────────────────────────────────────────────────────────────────────────
# Membership helpers
# ─────────────────────────────────────────────────────────────────────────────

async def get_membership(
    db: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrganizationMember | None:
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == MemberStatus.ACTIVE,
        )
    )
    return res.scalar_one_or_none()


async def _get_org_or_404(db: AsyncSession, org_id: uuid.UUID) -> Organization:
    res = await db.execute(select(Organization).where(Organization.id == org_id))
    org = res.scalar_one_or_none()
    if not org:
        raise NotFoundError("Организация не найдена")
    return org


async def _require_member(db: AsyncSession, org_id: uuid.UUID, user: User) -> Organization:
    """Любой активный участник или сотрудник BaltOIL."""
    org = await _get_org_or_404(db, org_id)
    if user.role in _STAFF_ROLES:
        return org
    if not await get_membership(db, org_id, user.id):
        raise ForbiddenError("Вы не участник этой организации")
    return org


async def _require_org_admin(db: AsyncSession, org_id: uuid.UUID, user: User) -> Organization:
    """Только owner организации или сотрудник BaltOIL — правка реквизитов/состава."""
    org = await _get_org_or_404(db, org_id)
    if user.role in _STAFF_ROLES:
        return org
    m = await get_membership(db, org_id, user.id)
    if not m or m.member_role != MemberRole.OWNER:
        raise ForbiddenError("Только владелец организации может это сделать")
    return org


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def create_organization(
    db: AsyncSession, owner: User, data: CreateOrganizationRequest
) -> Organization:
    api_key = get_settings().dadata_api_key
    party = await lookup_by_inn(data.inn, api_key) if api_key else None
    party = party or {}
    bank = await lookup_by_bik(data.bik, api_key) if (api_key and data.bik) else None
    bank = bank or {}

    company_name = _pick(data.company_name, party.get("company_name"))
    if not company_name:
        # Без названия организацию не создаём — но не блокируем при отказе DaData,
        # если клиент ввёл имя сам (см. _pick выше).
        raise ConflictError("Не удалось определить название организации — укажите его вручную")

    org = Organization(
        company_name=company_name,
        inn=data.inn,
        kpp=_pick(data.kpp, party.get("kpp")),
        ogrn=_pick(data.ogrn, party.get("ogrn")),
        legal_address=_pick(data.legal_address, party.get("legal_address")),
        delivery_address=data.delivery_address,
        bank_name=_pick(data.bank_name, bank.get("bank_name")),
        bik=data.bik,
        bank_account=data.bank_account,
        correspondent_account=_pick(data.correspondent_account, bank.get("correspondent_account")),
        swift=bank.get("swift"),
        contract_number=data.contract_number,
        billing_email=data.billing_email,
        okved=party.get("okved"),
        okpo=party.get("okpo"),
        okato=party.get("okato"),
        fns_status=party.get("fns_status"),
        director_name=party.get("director_name"),
        fns_last_sync_at=datetime.now(timezone.utc) if party else None,
    )
    db.add(org)
    await db.flush()

    # Владелец-участник. Staff (admin/manager) заводит организацию НА клиента.
    # Клиент-владелец необязателен (правки 2026-07-22): staff может создать
    # «ничейную» организацию (без участников) и вести заявки по ней сам;
    # при передаче клиенту — добавить его участником и «Сделать владельцем».
    owner_user_id: uuid.UUID | None
    if owner.role in _STAFF_ROLES:
        if data.owner_client_id:
            client = await db.get(User, data.owner_client_id)
            if client is None or client.role != UserRole.CLIENT:
                raise NotFoundError("Клиент-владелец не найден")
            owner_user_id = client.id
        else:
            owner_user_id = None
    else:
        owner_user_id = owner.id

    if owner_user_id is not None:
        db.add(OrganizationMember(
            organization_id=org.id,
            user_id=owner_user_id,
            member_role=MemberRole.OWNER,
            status=MemberStatus.ACTIVE,
        ))
    await db.commit()
    await db.refresh(org)
    return org


async def list_user_organizations(db: AsyncSession, user_id: uuid.UUID) -> list[Organization]:
    res = await db.execute(
        select(Organization)
        .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == MemberStatus.ACTIVE,
            Organization.is_archived == False,  # noqa: E712
        )
        .order_by(Organization.created_at.desc())
    )
    return list(res.scalars().all())


async def list_all_organizations(
    db: AsyncSession,
    search: str | None = None,
    include_archived: bool = False,
    offset: int = 0,
    limit: int = 200,
) -> list[Organization]:
    """Все организации (для admin/manager) — список + поиск по названию/ИНН."""
    conds = []
    if not include_archived:
        conds.append(Organization.is_archived == False)  # noqa: E712
    if search:
        like = f"%{search.strip()}%"
        conds.append(or_(Organization.company_name.ilike(like), Organization.inn.ilike(like)))
    stmt = (
        select(Organization)
        .where(*conds)
        .order_by(Organization.created_at.desc())
        .offset(offset).limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


async def update_organization(
    db: AsyncSession, org_id: uuid.UUID, actor: User, data: UpdateOrganizationRequest
) -> Organization:
    org = await _require_org_admin(db, org_id, actor)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    await db.commit()
    await db.refresh(org)
    return org


async def update_commercial(
    db: AsyncSession, org_id: uuid.UUID, data: UpdateOrganizationCommercialRequest
) -> Organization:
    """Тариф/кредит — вызывается только из admin-роута."""
    org = await _get_org_or_404(db, org_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org, field, value)
    await db.commit()
    await db.refresh(org)
    return org


async def archive_organization(db: AsyncSession, org_id: uuid.UUID, actor: User) -> None:
    org = await _require_org_admin(db, org_id, actor)
    org.is_archived = True
    org.archived_at = datetime.now(timezone.utc)
    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Members
# ─────────────────────────────────────────────────────────────────────────────

async def list_members(db: AsyncSession, org_id: uuid.UUID, actor: User) -> list[dict]:
    await _require_member(db, org_id, actor)
    res = await db.execute(
        select(OrganizationMember).where(OrganizationMember.organization_id == org_id)
    )
    members = list(res.scalars().all())
    user_ids = [m.user_id for m in members if m.user_id]
    users: dict[uuid.UUID, User] = {}
    if user_ids:
        ures = await db.execute(select(User).where(User.id.in_(user_ids)))
        users = {u.id: u for u in ures.scalars().all()}
    out = []
    for m in members:
        u = users.get(m.user_id) if m.user_id else None
        out.append({
            "id": m.id,
            "organization_id": m.organization_id,
            "user_id": m.user_id,
            "invite_phone": m.invite_phone,
            "member_role": m.member_role,
            "status": m.status,
            "created_at": m.created_at,
            "full_name": u.full_name if u else None,
            "phone": u.phone if u else m.invite_phone,
        })
    return out


async def add_member(
    db: AsyncSession, org_id: uuid.UUID, actor: User, phone: str
) -> OrganizationMember:
    """Добавить сотрудника по телефону. Если аккаунт есть — активный участник,
    иначе — pending-приглашение (привяжется при регистрации)."""
    await _require_org_admin(db, org_id, actor)
    norm = normalize_phone(phone)
    if len(norm) < 10:
        raise ConflictError("Некорректный номер телефона")

    # Ищем существующего активного пользователя по телефону
    res = await db.execute(
        select(User).where(
            User.phone.isnot(None),
            normalized_phone_column(User.phone) == norm,
            User.is_active == True,  # noqa: E712
            User.is_archived == False,  # noqa: E712
        )
    )
    user = res.scalars().first()

    if user:
        if await get_membership(db, org_id, user.id):
            raise ConflictError("Пользователь уже в организации")
        member = OrganizationMember(
            organization_id=org_id, user_id=user.id,
            member_role=MemberRole.MEMBER, status=MemberStatus.ACTIVE,
        )
    else:
        # pending-приглашение по номеру
        dup = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.invite_phone == norm,
                OrganizationMember.status == MemberStatus.PENDING,
            )
        )
        if dup.scalar_one_or_none():
            raise ConflictError("Приглашение на этот номер уже отправлено")
        member = OrganizationMember(
            organization_id=org_id, user_id=None, invite_phone=norm,
            member_role=MemberRole.MEMBER, status=MemberStatus.PENDING,
        )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return member


async def remove_member(
    db: AsyncSession, org_id: uuid.UUID, member_id: uuid.UUID, actor: User
) -> None:
    await _require_org_admin(db, org_id, actor)
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = res.scalar_one_or_none()
    if not member:
        raise NotFoundError("Участник не найден")
    if member.member_role == MemberRole.OWNER:
        # Нельзя удалить последнего владельца
        cnt = await db.execute(
            select(func.count()).select_from(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.member_role == MemberRole.OWNER,
                OrganizationMember.status == MemberStatus.ACTIVE,
            )
        )
        if (cnt.scalar() or 0) <= 1:
            raise ConflictError("Нельзя удалить единственного владельца организации")
    await db.delete(member)
    await db.commit()


async def set_owner(
    db: AsyncSession, org_id: uuid.UUID, member_id: uuid.UUID, actor: User
) -> None:
    """Сменить владельца организации. Выбранный участник становится владельцем,
    прежний(-ие) владелец(-цы) понижаются до сотрудника. Только staff BaltOIL —
    смена владельца затрагивает права на реквизиты и коммерческие условия."""
    if actor.role not in _STAFF_ROLES:
        raise ForbiddenError("Только сотрудник BaltOIL может сменить владельца")
    await _get_org_or_404(db, org_id)
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = res.scalar_one_or_none()
    if not member:
        raise NotFoundError("Участник не найден")
    if member.status != MemberStatus.ACTIVE or not member.user_id:
        raise ConflictError("Владельцем можно назначить только активного участника с аккаунтом")
    if member.member_role == MemberRole.OWNER:
        return  # уже владелец — идемпотентно

    cur = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.member_role == MemberRole.OWNER,
            OrganizationMember.status == MemberStatus.ACTIVE,
        )
    )
    for prev in cur.scalars().all():
        prev.member_role = MemberRole.MEMBER
    member.member_role = MemberRole.OWNER
    await db.commit()


async def link_pending_invites(db: AsyncSession, user: User) -> int:
    """Привязать pending-приглашения по телефону к новому пользователю.
    Вызывается при регистрации. Возвращает число привязанных приглашений."""
    if not user.phone:
        return 0
    norm = normalize_phone(user.phone)
    if len(norm) < 10:
        return 0
    res = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.invite_phone == norm,
            OrganizationMember.status == MemberStatus.PENDING,
        )
    )
    pending = list(res.scalars().all())
    for m in pending:
        m.user_id = user.id
        m.status = MemberStatus.ACTIVE
        m.invite_phone = None
    if pending:
        # flush, не commit: вызывается внутри транзакции регистрации (get_db коммитит сам)
        await db.flush()
    return len(pending)
