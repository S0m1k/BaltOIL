"""CRM-47: права на управление участниками групповых чатов.

Управлять составом приватной группы («СЗТК» и пр.) может администратор либо
создатель чата. Все остальные — включая менеджера-участника и водителя —
получают 403. Преднастроенные группы work/accounting составом не управляются:
их членство ролевое.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.core.dependencies import TokenUser
from app.models.conversation import Conversation, ConversationParticipant, ConversationKind
from app.services import conversation_service as cs


CREATOR_ID = uuid.uuid4()
ADMIN_ID = uuid.uuid4()
MANAGER_ID = uuid.uuid4()
DRIVER_ID = uuid.uuid4()


def _user(role: str, user_id: uuid.UUID) -> TokenUser:
    return TokenUser(id=user_id, role=role, name=role)


def _private_group(participant_ids: list[uuid.UUID] | None = None) -> Conversation:
    conv = Conversation(
        id=uuid.uuid4(),
        kind=ConversationKind.STAFF_GROUP,
        group_code=cs.PRIVATE_GROUP_PREFIX + uuid.uuid4().hex[:12],
        title="СЗТК",
        created_by_id=CREATOR_ID,
        created_by_role="manager",
        is_archived=False,
    )
    conv.participants = [
        ConversationParticipant(conversation_id=conv.id, user_id=uid, user_role="manager")
        for uid in (participant_ids if participant_ids is not None else [CREATOR_ID, MANAGER_ID])
    ]
    return conv


class _StubResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _StubSession:
    """Минимальный AsyncSession: отдаёт заранее заданный диалог на execute()."""

    def __init__(self, conv):
        self._conv = conv

    async def execute(self, _stmt):
        return _StubResult(self._conv)


# ── check_group_manage_access ────────────────────────────────────────────────

def test_admin_can_manage_group_members():
    cs.check_group_manage_access(_private_group(), _user("admin", ADMIN_ID))


def test_creator_can_manage_group_members():
    cs.check_group_manage_access(_private_group(), _user("manager", CREATOR_ID))


@pytest.mark.parametrize("role,user_id", [
    ("manager", MANAGER_ID),   # участник, но не создатель
    ("driver", DRIVER_ID),
    ("client", uuid.uuid4()),
])
def test_non_admin_non_creator_gets_403(role, user_id):
    with pytest.raises(HTTPException) as exc:
        cs.check_group_manage_access(_private_group(), _user(role, user_id))
    assert exc.value.status_code == 403


# ── _load_manageable_group ───────────────────────────────────────────────────

async def test_load_manageable_group_ok_for_admin():
    conv = _private_group()
    loaded = await cs._load_manageable_group(_StubSession(conv), conv.id, _user("admin", ADMIN_ID))
    assert loaded is conv


async def test_load_manageable_group_403_for_plain_manager():
    conv = _private_group()
    with pytest.raises(HTTPException) as exc:
        await cs._load_manageable_group(_StubSession(conv), conv.id, _user("manager", MANAGER_ID))
    assert exc.value.status_code == 403


async def test_preset_staff_group_membership_is_role_based():
    conv = Conversation(
        id=uuid.uuid4(),
        kind=ConversationKind.STAFF_GROUP,
        group_code="work",
        title="Работа",
        created_by_id=CREATOR_ID,
        created_by_role="system",
        is_archived=False,
    )
    conv.participants = []
    with pytest.raises(HTTPException) as exc:
        await cs._load_manageable_group(_StubSession(conv), conv.id, _user("admin", ADMIN_ID))
    assert exc.value.status_code == 403


async def test_direct_chat_is_not_manageable():
    conv = Conversation(
        id=uuid.uuid4(),
        kind=ConversationKind.DIRECT,
        client_id=ADMIN_ID,
        driver_id=DRIVER_ID,
        created_by_id=ADMIN_ID,
        created_by_role="user",
        is_archived=False,
    )
    conv.participants = []
    with pytest.raises(HTTPException) as exc:
        await cs._load_manageable_group(_StubSession(conv), conv.id, _user("admin", ADMIN_ID))
    assert exc.value.status_code == 403


async def test_missing_conversation_gives_404():
    with pytest.raises(HTTPException) as exc:
        await cs._load_manageable_group(_StubSession(None), uuid.uuid4(), _user("admin", ADMIN_ID))
    assert exc.value.status_code == 404


# ── remove_group_member: нельзя удалить создателя ────────────────────────────

async def test_cannot_remove_group_creator():
    conv = _private_group()
    with pytest.raises(HTTPException) as exc:
        await cs.remove_group_member(
            _StubSession(conv), _user("admin", ADMIN_ID), conv.id, CREATOR_ID
        )
    assert exc.value.status_code == 403


# ── доступ к чату после удаления ─────────────────────────────────────────────

def test_removed_member_loses_access():
    conv = _private_group(participant_ids=[CREATOR_ID])
    member_ids = {p.user_id for p in conv.participants}
    # Создатель остался — доступ есть
    cs._check_access(conv, _user("manager", CREATOR_ID), member_ids)
    # Удалённый менеджер — 403
    with pytest.raises(HTTPException) as exc:
        cs._check_access(conv, _user("manager", MANAGER_ID), member_ids)
    assert exc.value.status_code == 403
