"""Conversation service — snapshot-based membership model.

Three conversation kinds:
  client_manager      — one per client; managers/admins see all of them.
  client_driver_order — one per active order; client + assigned driver.
  staff_group         — pre-created groups: work (все staff), accounting (admin/manager).

Membership is enforced by snapshot fields in the Conversation row (client_id,
driver_id, order_id, group_code) — no RPC to auth_service needed for access checks.
ConversationParticipant is kept only for last_read_at (unread counters).
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from sqlalchemy import select, func, and_, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, with_loader_criteria
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

from app.models.conversation import Conversation, ConversationParticipant, ConversationKind
from app.models.message import Message
from app.schemas.message import MessageResponse
from app.core.dependencies import TokenUser
from app.core.exceptions import NotFoundError, ForbiddenError
from app.services import auth_client

# UUID used as sender_id for system messages
_SYSTEM_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")

# Преднастроенные групповые чаты сотрудников:
#   work       — «Работа»: водители + менеджеры + админы
#   accounting — «Бухгалтерия»: менеджеры + админы
STAFF_GROUPS = ("work", "accounting")
STAFF_GROUP_TITLES = {
    "work": "Работа",
    "accounting": "Бухгалтерия",
}
# Видимость предустановленных групп по роли — admin/manager видят work + accounting,
# driver только work.
STAFF_GROUP_ACCESS = {
    "admin":   {"work", "accounting"},
    "manager": {"work", "accounting"},
    "driver":  {"work"},
}
# Группы, доступные водителю (остальные staff-группы — только admin/manager).
DRIVER_STAFF_GROUPS = ("work",)

# Роли, формирующие состав преднастроенных групп (для эндпоинта /members):
#   work       — водители + менеджеры + админы
#   accounting — менеджеры + админы
STAFF_GROUP_MEMBER_ROLES = {
    "work": ("driver", "manager", "admin"),
    "accounting": ("manager", "admin"),
}
# Порядок ролей в выдаче состава (админы выше менеджеров выше водителей).
_ROLE_SORT_ORDER = {"admin": 0, "manager": 1, "driver": 2}

# Приватные групповые чаты сотрудников (правки 2026-06-23: чат «СЗТК» — конкретные
# участники, БЕЗ доступа остальных менеджеров/админов). group_code = "custom-<...>".
# В отличие от work/accounting доступ — по явному членству (ConversationParticipant),
# и проверяется ДО привилегии менеджеров (как DIRECT), иначе любой админ видел бы всё.
PRIVATE_GROUP_PREFIX = "custom-"


def _is_private_group(conv: "Conversation") -> bool:
    return (
        conv.kind == ConversationKind.STAFF_GROUP
        and bool(conv.group_code)
        and conv.group_code.startswith(PRIVATE_GROUP_PREFIX)
    )

MANAGER_ROLES = {"admin", "manager"}


# ─────────────────────────────────────────────────────────────────────────────
# Access control
# ─────────────────────────────────────────────────────────────────────────────

def _check_access(
    conv: Conversation, actor: TokenUser, member_ids: set | None = None
) -> None:
    """Raise ForbiddenError if the actor cannot access this conversation.

    member_ids — id участников (ConversationParticipant) для приватных групп;
    передаётся вызывающими, которые уже загрузили conv.participants.
    """
    # Прямой чат приватен — проверяем ДО привилегии менеджеров, иначе админ/менеджер
    # читали бы чужую личную переписку.
    if conv.kind == ConversationKind.DIRECT:
        if actor.id in (conv.client_id, conv.driver_id):
            return
        raise ForbiddenError("Это приватный чат")

    # Приватная staff-группа (СЗТК): только явные участники, ДО привилегии менеджеров.
    if _is_private_group(conv):
        if member_ids is not None and actor.id in member_ids:
            return
        raise ForbiddenError("Это приватный групповой чат")

    # Предустановленные группы (work/accounting): доступ по роли через
    # STAFF_GROUP_ACCESS — проверяем явно, не полагаясь на привилегию менеджеров.
    if conv.kind == ConversationKind.STAFF_GROUP and conv.group_code in STAFF_GROUPS:
        if conv.group_code in STAFF_GROUP_ACCESS.get(actor.role, set()):
            return
        raise ForbiddenError("У вас нет доступа к этому групповому чату")

    if actor.role in MANAGER_ROLES:
        return  # managers/admins see everything

    if conv.kind in (ConversationKind.CLIENT_MANAGER, ConversationKind.CLIENT_ACCOUNTANT):
        if actor.id == conv.client_id:
            return
        raise ForbiddenError("Это ваш диалог с менеджером")

    if conv.kind == ConversationKind.CLIENT_DRIVER_ORDER:
        if actor.id in (conv.client_id, conv.driver_id):
            return
        raise ForbiddenError("Вы не участник этого диалога")

    raise ForbiddenError("Доступ запрещён")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _auto_enroll(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Add actor to participants (for last_read_at tracking) if not already enrolled."""
    result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == actor.id,
        )
    )
    if not result.scalar_one_or_none():
        db.add(ConversationParticipant(
            conversation_id=conv_id,
            user_id=actor.id,
            user_role=actor.role,
            last_read_at=datetime.now(timezone.utc),
        ))


# ─────────────────────────────────────────────────────────────────────────────
# Ensure helpers (idempotent create-or-return)
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_client_manager(
    db: AsyncSession,
    client_id: uuid.UUID,
) -> Conversation:
    """Return existing client_manager conversation for this client, or create one."""
    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.CLIENT_MANAGER,
            Conversation.client_id == client_id,
            Conversation.is_archived == False,  # noqa: E712
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        kind=ConversationKind.CLIENT_MANAGER,
        client_id=client_id,
        created_by_id=_SYSTEM_UUID,
        created_by_role="system",
    )
    db.add(conv)
    await db.flush()
    return conv


async def ensure_client_accountant(
    db: AsyncSession,
    client_id: uuid.UUID,
) -> Conversation:
    """Чат клиента-юрлица с бухгалтерией (правки 2026-06-11).

    Один на клиента, как client_manager. Видят клиент + менеджеры/админы.
    Проверка client_type=company — на вызывающей стороне (роутер).
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.CLIENT_ACCOUNTANT,
            Conversation.client_id == client_id,
            Conversation.is_archived == False,  # noqa: E712
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        kind=ConversationKind.CLIENT_ACCOUNTANT,
        client_id=client_id,
        title="Бухгалтерия",
        created_by_id=_SYSTEM_UUID,
        created_by_role="system",
    )
    db.add(conv)
    await db.flush()
    return conv


async def ensure_client_driver_order(
    db: AsyncSession,
    order_id: uuid.UUID,
    client_id: uuid.UUID,
    driver_id: uuid.UUID,
    driver_name: str = "",
    order_number: str = "",
    redis: aioredis.Redis | None = None,
) -> Conversation:
    """Return existing client_driver_order conversation for this order, or create one.

    Called by order_service when a driver claims an order.
    """
    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
            Conversation.order_id == order_id,
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        # Update driver_id if it changed (shouldn't happen normally)
        if conv.driver_id != driver_id:
            conv.driver_id = driver_id
        return conv

    title = f"Заявка {order_number}" if order_number else None
    conv = Conversation(
        kind=ConversationKind.CLIENT_DRIVER_ORDER,
        client_id=client_id,
        driver_id=driver_id,
        order_id=order_id,
        title=title,
        created_by_id=_SYSTEM_UUID,
        created_by_role="system",
    )
    db.add(conv)
    await db.flush()

    # Системное сообщение «Водитель принял заявку» убрано (правки 2026-06-23):
    # заказчик счёл его лишним шумом в рабочих чатах. Диалог создаётся молча —
    # участники видят его в списке и так.

    return conv


async def ensure_direct(
    db: AsyncSession,
    initiator_id: uuid.UUID,
    target_id: uuid.UUID,
) -> Conversation:
    """Вернуть существующий прямой чат между двумя пользователями или создать новый.

    Членство хранится в client_id (инициатор) и driver_id (собеседник); порядок
    при поиске не важен. Идемпотентно — повторный вызов вернёт тот же диалог.
    """
    if initiator_id == target_id:
        raise ForbiddenError("Нельзя начать чат с самим собой")

    result = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.DIRECT,
            Conversation.is_archived == False,  # noqa: E712
            or_(
                and_(Conversation.client_id == initiator_id, Conversation.driver_id == target_id),
                and_(Conversation.client_id == target_id, Conversation.driver_id == initiator_id),
            ),
        )
    )
    conv = result.scalar_one_or_none()
    if conv:
        return conv

    conv = Conversation(
        kind=ConversationKind.DIRECT,
        client_id=initiator_id,
        driver_id=target_id,
        created_by_id=initiator_id,
        created_by_role="user",
    )
    db.add(conv)
    await db.flush()
    return conv


# ─────────────────────────────────────────────────────────────────────────────
# Staff group bootstrap (called at app startup)
# ─────────────────────────────────────────────────────────────────────────────

async def ensure_staff_groups(db: AsyncSession) -> None:
    """Привести staff-группы к актуальному набору (work / accounting), идемпотентно.

    - создаёт отсутствующие группы из STAFF_GROUPS;
    - архивирует устаревшие staff-группы (старые general/drivers/managers),
      чтобы они исчезли из списков после рефакторинга чатов.
    """
    for code in STAFF_GROUPS:
        result = await db.execute(
            select(Conversation).where(
                Conversation.kind == ConversationKind.STAFF_GROUP,
                Conversation.group_code == code,
            )
        )
        conv = result.scalar_one_or_none()
        if conv:
            # На случай повторного запуска — снимаем архив и чиним заголовок.
            conv.is_archived = False
            conv.title = STAFF_GROUP_TITLES.get(code, code)
            continue

        db.add(Conversation(
            kind=ConversationKind.STAFF_GROUP,
            group_code=code,
            title=STAFF_GROUP_TITLES.get(code, code),
            created_by_id=_SYSTEM_UUID,
            created_by_role="system",
        ))

    # Архивируем устаревшие staff-группы (старые general/drivers/managers).
    # Приватные группы (custom-*) НЕ трогаем — это пользовательские чаты вроде СЗТК.
    stale = await db.execute(
        select(Conversation).where(
            Conversation.kind == ConversationKind.STAFF_GROUP,
            Conversation.group_code.notin_(STAFF_GROUPS),
            Conversation.group_code.notlike(f"{PRIVATE_GROUP_PREFIX}%"),
            Conversation.is_archived == False,  # noqa: E712
        )
    )
    for conv in stale.scalars().all():
        conv.is_archived = True

    await db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Приватные групповые чаты сотрудников (СЗТК и пр.)
# ─────────────────────────────────────────────────────────────────────────────

async def _load_private_group(db: AsyncSession, conv_id: uuid.UUID) -> Conversation:
    res = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.participants))
        .where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = res.scalar_one_or_none()
    if not conv or not _is_private_group(conv):
        raise NotFoundError("Групповой чат не найден")
    return conv


async def create_private_group(
    db: AsyncSession, actor: TokenUser, title: str, member_ids: list[uuid.UUID]
) -> Conversation:
    """Создать приватный групповой чат сотрудников с явным составом участников.

    Создатель всегда входит в состав. Доступ к чату — только у участников
    (см. _check_access / list_conversations). Только staff (admin/manager).
    """
    if actor.role not in MANAGER_ROLES:
        raise ForbiddenError("Создавать групповые чаты может менеджер или администратор")
    ids: set[uuid.UUID] = set(member_ids) | {actor.id}
    code = PRIVATE_GROUP_PREFIX + uuid.uuid4().hex[:12]
    conv = Conversation(
        kind=ConversationKind.STAFF_GROUP,
        group_code=code,
        title=(title or "").strip() or "Группа",
        created_by_id=actor.id,
        created_by_role=actor.role,
    )
    db.add(conv)
    await db.flush()

    contacts = await auth_client.get_contacts(list(ids))
    now = datetime.now(timezone.utc)
    for uid in ids:
        role = (contacts.get(str(uid)) or {}).get("role") or "manager"
        db.add(ConversationParticipant(
            conversation_id=conv.id,
            user_id=uid,
            user_role=role,
            last_read_at=now if uid == actor.id else None,
        ))
    await db.flush()
    return conv


async def set_private_group_members(
    db: AsyncSession, actor: TokenUser, conv_id: uuid.UUID, member_ids: list[uuid.UUID]
) -> Conversation:
    """Заменить состав участников приватной группы. Доступно текущим участникам-staff."""
    conv = await _load_private_group(db, conv_id)
    member_set = {p.user_id for p in conv.participants}
    if actor.role not in MANAGER_ROLES or actor.id not in member_set:
        raise ForbiddenError("Менять состав может только участник-сотрудник")

    # Создатель и текущий actor всегда остаются — чтобы группа не осталась без владельца.
    wanted: set[uuid.UUID] = set(member_ids) | {actor.id, conv.created_by_id}
    existing = {p.user_id: p for p in conv.participants}

    # Удаляем выбывших
    for uid, part in existing.items():
        if uid not in wanted:
            await db.delete(part)

    # Добавляем новых
    to_add = wanted - set(existing.keys())
    if to_add:
        contacts = await auth_client.get_contacts(list(to_add))
        for uid in to_add:
            role = (contacts.get(str(uid)) or {}).get("role") or "manager"
            db.add(ConversationParticipant(
                conversation_id=conv.id, user_id=uid, user_role=role, last_read_at=None,
            ))
    await db.flush()
    return conv


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def get_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
) -> Conversation:
    result = await db.execute(
        select(Conversation)
        .options(
            selectinload(Conversation.participants),
            selectinload(Conversation.messages),
            # Не отдаём soft-deleted сообщения: иначе удалённое сообщение всплывало
            # снова при переоткрытии диалога (в отличие от /messages, который их прячет).
            with_loader_criteria(Message, Message.is_archived == False),  # noqa: E712
        )
        .where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")

    _check_access(conv, actor, {p.user_id for p in conv.participants})
    await _auto_enroll(db, conv_id, actor)
    await db.commit()
    await db.refresh(conv, ["participants"])

    # Обогащаем участников именем и телефоном (задача: телефоны видны в чате).
    # Для прямого чата дополнительно резолвим собеседника, даже если он ещё не
    # открывал диалог и потому отсутствует в таблице participants.
    wanted: set[uuid.UUID] = {p.user_id for p in conv.participants}
    if conv.kind == ConversationKind.DIRECT:
        if conv.client_id:
            wanted.add(conv.client_id)
        if conv.driver_id:
            wanted.add(conv.driver_id)
    contacts = await auth_client.get_contacts(list(wanted)) if wanted else {}

    for p in conv.participants:
        card = contacts.get(str(p.user_id))
        p.full_name = card.get("full_name") if card else None
        p.phone = card.get("phone") if card else None

    conv.peer_name = conv.peer_phone = None
    if conv.kind == ConversationKind.DIRECT:
        peer_id = conv.driver_id if conv.client_id == actor.id else conv.client_id
        card = contacts.get(str(peer_id)) if peer_id else None
        if card:
            conv.peer_name = card.get("full_name")
            conv.peer_phone = card.get("phone")

    return conv


async def get_conversation_members(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
) -> list[dict]:
    """Состав группового чата для отображения в UI (задача: «состав» виден явно).

    Для преднастроенных групп (work/accounting) членство ролевое — вычисляем
    его на лету через auth_service (users-by-role + contacts), а не читаем
    ConversationParticipant. Для прочих kind — явный список участников.
    """
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.participants))
        .where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")

    _check_access(conv, actor, {p.user_id for p in conv.participants})

    if conv.kind == ConversationKind.STAFF_GROUP and conv.group_code in STAFF_GROUP_MEMBER_ROLES:
        roles = STAFF_GROUP_MEMBER_ROLES[conv.group_code]
        user_ids = await auth_client.get_users_by_role(list(roles))
        if not user_ids:
            return []
        contacts = await auth_client.get_contacts(user_ids)
        members = []
        for uid in user_ids:
            card = contacts.get(str(uid))
            if not card:
                # Контакт не резолвился (auth_service недоступен/удалён) — пропускаем,
                # не показываем «голый» id без имени и роли.
                continue
            members.append({
                "id": uid,
                "full_name": card.get("full_name"),
                "role": card.get("role") or "manager",
            })
        members.sort(key=lambda m: (_ROLE_SORT_ORDER.get(m["role"], 9), m["full_name"] or ""))
        return members

    # Прочие kind — явный список участников (ConversationParticipant).
    ids = [p.user_id for p in conv.participants]
    contacts = await auth_client.get_contacts(ids) if ids else {}
    members = [
        {
            "id": p.user_id,
            "full_name": (contacts.get(str(p.user_id)) or {}).get("full_name"),
            "role": p.user_role,
        }
        for p in conv.participants
    ]
    members.sort(key=lambda m: (_ROLE_SORT_ORDER.get(m["role"], 9), m["full_name"] or ""))
    return members


async def list_conversations(
    db: AsyncSession,
    actor: TokenUser,
    order_id: uuid.UUID | None = None,  # kept for API compatibility, not used in new model
) -> list[dict]:
    """List conversations visible to this actor with unread counts and last message."""
    role = actor.role

    # ── Build visibility filter ───────────────────────────────────────────────
    if role == "client":
        # Auto-create client_manager if it doesn't exist yet
        cm = await ensure_client_manager(db, actor.id)
        await db.commit()

        visibility = or_(
            and_(
                Conversation.kind.in_([
                    ConversationKind.CLIENT_MANAGER,
                    ConversationKind.CLIENT_ACCOUNTANT,
                ]),
                Conversation.client_id == actor.id,
            ),
            and_(
                Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
                Conversation.client_id == actor.id,
                Conversation.is_archived == False,  # noqa: E712
            ),
        )
    elif role == "driver":
        visibility = or_(
            and_(
                Conversation.kind == ConversationKind.STAFF_GROUP,
                Conversation.group_code.in_(list(DRIVER_STAFF_GROUPS)),
            ),
            and_(
                Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
                Conversation.driver_id == actor.id,
                Conversation.is_archived == False,  # noqa: E712
            ),
        )
    else:  # manager / admin
        visibility = or_(
            and_(
                Conversation.kind == ConversationKind.STAFF_GROUP,
                Conversation.group_code.in_(list(STAFF_GROUP_ACCESS.get(role, set()))),
            ),
            Conversation.kind.in_([
                ConversationKind.CLIENT_MANAGER,
                ConversationKind.CLIENT_ACCOUNTANT,
            ]),
            and_(
                Conversation.kind == ConversationKind.CLIENT_DRIVER_ORDER,
                Conversation.is_archived == False,  # noqa: E712
            ),
        )

    # Прямые чаты видны их двум участникам независимо от роли.
    direct_vis = and_(
        Conversation.kind == ConversationKind.DIRECT,
        or_(Conversation.client_id == actor.id, Conversation.driver_id == actor.id),
    )

    # Приватные staff-группы (СЗТК) — видны только своим участникам (по членству).
    private_vis = and_(
        Conversation.kind == ConversationKind.STAFF_GROUP,
        Conversation.group_code.like(f"{PRIVATE_GROUP_PREFIX}%"),
        Conversation.id.in_(
            select(ConversationParticipant.conversation_id).where(
                ConversationParticipant.user_id == actor.id
            )
        ),
    )

    q = (
        select(Conversation)
        .where(Conversation.is_archived == False, or_(visibility, direct_vis, private_vis))  # noqa: E712
        .order_by(Conversation.updated_at.desc())
    )
    result = await db.execute(q)
    conversations = result.scalars().all()

    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]

    # ── Unread counts ─────────────────────────────────────────────────────────
    actor_part_alias = ConversationParticipant.__table__.alias("actor_part")
    unread_q = (
        select(
            Message.conversation_id,
            func.count(Message.id).label("unread"),
        )
        .join(
            actor_part_alias,
            and_(
                actor_part_alias.c.conversation_id == Message.conversation_id,
                actor_part_alias.c.user_id == actor.id,
            ),
            isouter=True,
        )
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.is_archived == False,  # noqa: E712
            Message.sender_id != actor.id,
            (actor_part_alias.c.last_read_at.is_(None))
            | (Message.created_at > actor_part_alias.c.last_read_at),
        )
        .group_by(Message.conversation_id)
    )
    unread_res = await db.execute(unread_q)
    unread_counts: dict[uuid.UUID, int] = {
        row.conversation_id: row.unread for row in unread_res
    }

    # ── Last message per conversation ─────────────────────────────────────────
    max_ts_subq = (
        select(
            Message.conversation_id.label("conv_id"),
            func.max(Message.created_at).label("max_ts"),
        )
        .where(
            Message.conversation_id.in_(conv_ids),
            Message.is_archived == False,  # noqa: E712
        )
        .group_by(Message.conversation_id)
        .subquery()
    )
    last_msgs_result = await db.execute(
        select(Message).join(
            max_ts_subq,
            and_(
                Message.conversation_id == max_ts_subq.c.conv_id,
                Message.created_at == max_ts_subq.c.max_ts,
            ),
        ).where(Message.is_archived == False)  # noqa: E712
    )
    last_msgs: dict[uuid.UUID, Message] = {
        m.conversation_id: m for m in last_msgs_result.scalars().all()
    }

    # ── Закреплённые чаты текущего пользователя (правки 2026-06-11) ──────────
    pins_res = await db.execute(
        select(ConversationParticipant.conversation_id).where(
            ConversationParticipant.conversation_id.in_(conv_ids),
            ConversationParticipant.user_id == actor.id,
            ConversationParticipant.is_pinned == True,  # noqa: E712
        )
    )
    pinned_ids = {row[0] for row in pins_res.all()}

    # Для прямых чатов резолвим «собеседника» (имя + телефон), чтобы фронт показал
    # его в заголовке/списке. Один батч-запрос на все peer-id.
    peer_ids = [
        (c.driver_id if c.client_id == actor.id else c.client_id)
        for c in conversations
        if c.kind == ConversationKind.DIRECT
    ]
    contacts = await auth_client.get_contacts(peer_ids) if peer_ids else {}

    output = []
    for conv in conversations:
        last_msg = last_msgs.get(conv.id)
        peer_name = peer_phone = peer_role = None
        peer_id_val = None
        if conv.kind == ConversationKind.DIRECT:
            peer_id = conv.driver_id if conv.client_id == actor.id else conv.client_id
            peer_id_val = peer_id
            card = contacts.get(str(peer_id)) if peer_id else None
            if card:
                peer_name = card.get("full_name")
                peer_phone = card.get("phone")
                # Роль собеседника (правки 2026-07-11): фронт кладёт личные чаты
                # с сотрудниками в папку «Работа», с клиентами — в «Личные».
                peer_role = card.get("role")
        output.append({
            "id": conv.id,
            "kind": conv.kind,
            "title": conv.title,
            "client_id": conv.client_id,
            "driver_id": conv.driver_id,
            "order_id": conv.order_id,
            "group_code": conv.group_code,
            "created_by_id": conv.created_by_id,
            "created_by_role": conv.created_by_role,
            "unread_count": unread_counts.get(conv.id, 0),
            "last_message": MessageResponse.model_validate(last_msg) if last_msg else None,
            "updated_at": conv.updated_at,
            "peer_name": peer_name,
            "peer_phone": peer_phone,
            "peer_role": peer_role,
            "peer_id": peer_id_val,
            "is_pinned": conv.id in pinned_ids,
        })

    # Закреплённые — первыми, внутри групп сортировка по updated_at сохраняется
    output.sort(key=lambda r: (not r["is_pinned"],))
    return output


async def set_pinned(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
    is_pinned: bool,
) -> None:
    """Закрепить/открепить чат для текущего пользователя (правки 2026-06-11)."""
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.participants))
        .where(
            Conversation.id == conv_id, Conversation.is_archived == False  # noqa: E712
        )
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")
    _check_access(conv, actor, {p.user_id for p in conv.participants})

    part_res = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == actor.id,
        )
    )
    participant = part_res.scalar_one_or_none()
    if participant:
        participant.is_pinned = is_pinned
    else:
        db.add(ConversationParticipant(
            conversation_id=conv_id,
            user_id=actor.id,
            user_role=actor.role,
            is_pinned=is_pinned,
        ))
    await db.commit()


async def mark_read(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    result = await db.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conv_id,
            ConversationParticipant.user_id == actor.id,
        )
    )
    participant = result.scalar_one_or_none()
    if participant:
        participant.last_read_at = datetime.now(timezone.utc)
    else:
        # Auto-enroll and mark read simultaneously
        db.add(ConversationParticipant(
            conversation_id=conv_id,
            user_id=actor.id,
            user_role=actor.role,
            last_read_at=datetime.now(timezone.utc),
        ))
    await db.commit()


async def archive_conversation(db: AsyncSession, conv_id: uuid.UUID, actor: TokenUser) -> None:
    """Archive a conversation — manager/admin only."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")
    if actor.role not in MANAGER_ROLES:
        raise ForbiddenError("Только менеджер или администратор может архивировать диалог")
    conv.is_archived = True
    await db.commit()


async def delete_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
    redis: aioredis.Redis,
) -> None:
    """Hard-delete — admin only."""
    if actor.role != "admin":
        raise ForbiddenError("Удалить диалог полностью может только администратор")
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise NotFoundError("Диалог не найден")
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.execute(
        delete(ConversationParticipant).where(ConversationParticipant.conversation_id == conv_id)
    )
    await db.delete(conv)
    await db.commit()
    try:
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "event": "conversation_deleted",
            "conversation_id": str(conv_id),
        }))
    except Exception:
        logger.exception("Failed to publish conversation_deleted event")


async def clear_conversation(
    db: AsyncSession,
    conv_id: uuid.UUID,
    actor: TokenUser,
    redis: aioredis.Redis,
) -> None:
    """Clear message history — admin only."""
    if actor.role != "admin":
        raise ForbiddenError("Очистить историю может только администратор")
    result = await db.execute(
        select(Conversation).where(Conversation.id == conv_id, Conversation.is_archived == False)  # noqa: E712
    )
    if not result.scalar_one_or_none():
        raise NotFoundError("Диалог не найден")
    await db.execute(delete(Message).where(Message.conversation_id == conv_id))
    await db.commit()
    try:
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "event": "conversation_cleared",
            "conversation_id": str(conv_id),
        }))
    except Exception:
        logger.exception("Failed to publish conversation_cleared event")


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _post_system_message_raw(
    db: AsyncSession,
    conv_id: uuid.UUID,
    text: str,
    redis: aioredis.Redis,
) -> None:
    """Post a system message without going through message_service (avoids circular import)."""
    from app.models.message import Message as _Message
    msg = _Message(
        conversation_id=conv_id,
        sender_id=_SYSTEM_UUID,
        sender_role="system",
        sender_name="Система",  # Message.sender_name NOT NULL — иначе INSERT падает 500
        text=text,
        msg_type="system",
    )
    db.add(msg)
    await db.flush()

    # Update conversation updated_at
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if conv:
        conv.updated_at = datetime.now(timezone.utc)

    try:
        # Плоский payload — как message_service.post_system_message и websocket.py.
        # Раньше слался вложенный {event, message}, который фронт (ws.onmessage ждёт
        # плоскую структуру) не мог отрисовать → битый пузырь до перезагрузки.
        await redis.publish(f"chat:{conv_id}", json.dumps({
            "id": str(msg.id),
            "conversation_id": str(conv_id),
            "sender_id": str(_SYSTEM_UUID),
            "sender_role": "system",
            "sender_name": "Система",
            "msg_type": "system",
            "text": text,
            "metadata": None,
            "created_at": msg.created_at.isoformat() if hasattr(msg, "created_at") and msg.created_at else None,
        }))
    except Exception:
        logger.warning("Failed to publish system message event for conv %s", conv_id)
