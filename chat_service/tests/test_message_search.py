"""Поиск по сообщениям (правки 2026-09-21).

Живая БД не нужна: подставляем стаб-сессию и проверяем сам запрос — что
ищется по тексту, что область ограничена видимыми диалогами и что лимит
не раздувается по просьбе клиента.
"""
import uuid

import pytest
from sqlalchemy.dialects import postgresql

from app.core.dependencies import TokenUser
from app.core.exceptions import ValidationError
from app.services import message_service as ms


class _StubResult:
    def all(self):
        return []


class _StubSession:
    """Запоминает выполненный запрос вместо похода в базу."""

    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _StubResult()


def _user(role: str = "manager") -> TokenUser:
    return TokenUser(id=uuid.uuid4(), role=role, name=role)


async def _run(query: str, **kwargs):
    db = _StubSession()
    await ms.search_messages(db, kwargs.pop("actor", _user()), query, **kwargs)
    # Компилируем под Postgres — как в бою: на «диалекте по умолчанию»
    # ilike превращается в lower(...) LIKE lower(...), и тест проверял бы не то.
    compiled = db.statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


# ── Что именно ищем ───────────────────────────────────────────────────────────

async def test_searches_by_message_text_case_insensitively():
    sql, params = await _run("Накладная")
    assert "ILIKE" in sql.upper()
    assert "%Накладная%" in params.values()


async def test_percent_sign_is_searched_as_text_not_as_wildcard():
    # «скидка 20%» не должна превращаться в «найди вообще всё».
    _, params = await _run("скидка 20%")
    assert "%скидка 20\\%%" in params.values()


async def test_underscore_is_escaped_too():
    _, params = await _run("файл_1")
    assert "%файл\\_1%" in params.values()


@pytest.mark.parametrize("bad", ["", " ", "а", "  x  "[:3]])
async def test_too_short_query_is_rejected(bad):
    with pytest.raises(ValidationError):
        await _run(bad)


async def test_newest_messages_come_first():
    sql, _ = await _run("оплата")
    assert "ORDER BY messages.created_at DESC" in sql


# ── Границы выдачи ────────────────────────────────────────────────────────────

async def test_limit_is_capped_even_if_client_asks_for_more():
    _, params = await _run("оплата", limit=100000)
    assert ms.MAX_SEARCH_RESULTS in params.values()


async def test_limit_below_one_falls_back_to_one():
    _, params = await _run("оплата", limit=0)
    assert 1 in params.values()


async def test_search_can_be_narrowed_to_one_conversation():
    conv_id = uuid.uuid4()
    sql, params = await _run("оплата", conversation_id=conv_id)
    assert "messages.conversation_id =" in sql
    assert conv_id in params.values()


# ── Область поиска = то, что человеку и так видно ─────────────────────────────

async def test_archived_messages_and_chats_are_skipped():
    sql, _ = await _run("оплата")
    assert "messages.is_archived = false" in sql
    assert "conversations.is_archived = false" in sql


@pytest.mark.parametrize("role", ["admin", "manager", "driver", "client"])
async def test_scope_is_limited_by_conversation_visibility(role):
    # Условие видимости — то же, что у списка чатов: поиск не должен
    # показывать куски переписки, которой в списке нет.
    sql, _ = await _run("оплата", actor=_user(role))
    assert "conversations.kind" in sql
    # Личные чаты — только свои, независимо от роли.
    assert "conversations.client_id =" in sql and "conversations.driver_id =" in sql


async def test_driver_sees_private_groups_only_by_membership():
    sql, _ = await _run("оплата", actor=_user("driver"))
    assert "conversation_participants" in sql


async def test_admin_sees_every_private_group():
    # Админ модерирует все группы (правки 2026-07-25) — членство не требуется.
    sql, _ = await _run("оплата", actor=_user("admin"))
    assert "conversations.group_code LIKE" in sql
