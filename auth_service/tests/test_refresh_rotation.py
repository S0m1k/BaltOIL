"""Гонка ротации refresh-токенов.

Сценарий из прода: две вкладки одновременно дёргают /auth/refresh. Победившая
ротирует токен, проигравшая присылает тот же (уже ротированный) токен на
миллисекунды позже. Раньше это трактовалось как кража и гасило ВСЕ сессии
пользователя. Теперь повтор внутри grace-окна — легитимный дубль.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.exceptions import AuthError
from app.core.security import (
    generate_refresh_token,
    hash_password,
    hash_token,
    refresh_token_expires_at,
)
from app.models.audit_log import AuditLog
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole
from app.services import auth_service


async def _make_user(db) -> User:
    user = User(
        email="race@example.com",
        phone="+79990000001",
        hashed_password=hash_password("Password123"),
        role=UserRole.MANAGER,
        full_name="Гонщиков Иван",
    )
    db.add(user)
    await db.flush()
    return user


async def _login(db, user: User) -> str:
    """Выдать пользователю refresh-токен «как при логине».

    Не зовём auth_service.login() намеренно: он ходит в Redis (login_throttle),
    которого в тестовом окружении нет, а сама проверка гонки от логина не зависит.
    """
    raw = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=refresh_token_expires_at(),
        )
    )
    await db.commit()
    return raw


async def _token_row(db, raw: str) -> RefreshToken | None:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw))
    )
    return result.scalar_one_or_none()


async def _actions(db) -> list[str]:
    result = await db.execute(select(AuditLog.action))
    return list(result.scalars().all())


async def test_rotation_marks_revoked_at_and_successor(db):
    user = await _make_user(db)
    raw = await _login(db, user)

    resp = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()

    old = await _token_row(db, raw)
    new = await _token_row(db, resp.refresh_token)

    assert old.is_revoked is True
    assert old.revoked_at is not None
    assert old.rotated_to_id == new.id
    assert new.is_revoked is False
    assert new.revoked_at is None


async def test_duplicate_refresh_within_grace_issues_new_pair(db):
    """(a) Повтор ротированного токена внутри grace → 2 валидные пары, никого не разлогинило."""
    user = await _make_user(db)
    raw = await _login(db, user)

    first = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()

    # Проигравшая вкладка присылает тот же старый токен спустя миллисекунды.
    second = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()

    assert second.refresh_token != first.refresh_token

    # Обе выданные пары живы — никого не разлогинило.
    for raw_token in (first.refresh_token, second.refresh_token):
        row = await _token_row(db, raw_token)
        assert row is not None and row.is_revoked is False

    actions = await _actions(db)
    assert "user.refresh_token_reuse_detected" not in actions
    assert actions.count("user.token_refresh") == 2

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user.token_refresh")
    )
    details = [entry.details for entry in result.scalars().all()]
    assert {"duplicate_within_grace": True} in details

    # Обе новые пары остаются рабочими: следующий refresh проходит штатно.
    third = await auth_service.refresh_tokens(
        db, raw_refresh_token=first.refresh_token
    )
    await db.commit()
    assert third.refresh_token


async def _age_out_of_grace(db, raw: str) -> None:
    """Отмотать revoked_at токена за пределы grace-окна."""
    grace = auth_service.get_settings().refresh_rotation_grace_seconds
    row = await _token_row(db, raw)
    row.revoked_at = datetime.now(timezone.utc) - timedelta(seconds=grace + 5)
    await db.commit()


async def test_lost_refresh_response_outside_grace_issues_new_pair(db):
    """(b) Мобильный клиент не получил ответ на refresh — не кража.

    Android убивает процесс, сеть рвётся в дороге: сервер пару ротировал, а
    телефон о ней не узнал и на следующем запуске предъявляет прежний токен.
    Наследника при этом НИКТО не предъявлял — второго владельца пары нет.
    Раньше здесь срабатывал logout_all, и человек логинился заново каждый
    запуск приложения.
    """
    user = await _make_user(db)
    raw = await _login(db, user)

    lost = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()
    await _age_out_of_grace(db, raw)

    again = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()

    assert again.refresh_token
    assert "user.refresh_token_reuse_detected" not in await _actions(db)
    # Неполученный наследник погашен: действующей остаётся ровно одна пара.
    assert (await _token_row(db, lost.refresh_token)).is_revoked is True
    assert (await _token_row(db, again.refresh_token)).is_revoked is False

    result = await db.execute(
        select(AuditLog).where(AuditLog.action == "user.token_refresh")
    )
    assert {"lost_refresh_response": True} in [
        entry.details for entry in result.scalars().all()
    ]


async def test_reuse_with_spent_successor_is_treated_as_theft(db):
    """(b2) Наследник уже потрачен → пару держат двое → сносим все сессии.

    Это и есть настоящая кража: легитимный клиент ответ получил и наследником
    воспользовался, значит старый токен предъявляет кто-то ещё.
    """
    user = await _make_user(db)
    raw = await _login(db, user)

    second = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()
    # Легитимный клиент воспользовался наследником — тот больше не «нетронут».
    third = await auth_service.refresh_tokens(
        db, raw_refresh_token=second.refresh_token
    )
    await db.commit()
    await _age_out_of_grace(db, raw)

    with pytest.raises(AuthError):
        await auth_service.refresh_tokens(db, raw_refresh_token=raw)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    tokens = list(result.scalars().all())
    assert tokens and all(t.is_revoked for t in tokens)
    assert (await _token_row(db, third.refresh_token)).is_revoked is True
    assert "user.refresh_token_reuse_detected" in await _actions(db)


async def test_stolen_token_is_caught_when_real_client_returns(db):
    """Кража украденного токена не даёт злоумышленнику тихой сессии.

    Вор предъявляет старый токен первым и получает пару (наследник выглядел
    нетронутым). Но настоящий клиент приходит со СВОИМ наследником — тот уже
    отозван и без rotated_to_id, — и это гасит все сессии обоих.
    """
    user = await _make_user(db)
    raw = await _login(db, user)

    victim = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()
    await _age_out_of_grace(db, raw)

    thief = await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()
    assert thief.refresh_token

    with pytest.raises(AuthError):
        await auth_service.refresh_tokens(db, raw_refresh_token=victim.refresh_token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.user_id == user.id)
    )
    tokens = list(result.scalars().all())
    assert tokens and all(t.is_revoked for t in tokens), "сессия вора тоже убита"
    assert (await _token_row(db, thief.refresh_token)).is_revoked is True
    assert "user.refresh_token_reuse_detected" in await _actions(db)


async def test_legacy_revoked_at_null_is_treated_as_theft(db):
    """Строки, отозванные ДО миграции 0013 (revoked_at NULL), — старое поведение."""
    user = await _make_user(db)
    raw = await _login(db, user)

    await auth_service.refresh_tokens(db, raw_refresh_token=raw)
    await db.commit()

    old = await _token_row(db, raw)
    old.revoked_at = None
    old.rotated_to_id = None
    await db.commit()

    with pytest.raises(AuthError):
        await auth_service.refresh_tokens(db, raw_refresh_token=raw)

    assert "user.refresh_token_reuse_detected" in await _actions(db)


async def test_reuse_after_logout_is_theft_even_within_grace(db):
    """(c) Повтор токена после logout → ветка «кража» даже внутри 60 с."""
    user = await _make_user(db)
    raw = await _login(db, user)

    await auth_service.logout(db, raw_refresh_token=raw, actor_id=user.id)
    await db.commit()

    row = await _token_row(db, raw)
    assert row.is_revoked is True
    assert row.revoked_at is not None
    # logout НЕ ротация — преемника нет.
    assert row.rotated_to_id is None

    with pytest.raises(AuthError):
        await auth_service.refresh_tokens(db, raw_refresh_token=raw)

    assert "user.refresh_token_reuse_detected" in await _actions(db)


async def test_reuse_after_logout_all_is_theft_even_within_grace(db):
    user = await _make_user(db)
    raw = await _login(db, user)

    await auth_service.logout_all(db, user_id=user.id)
    await db.commit()

    row = await _token_row(db, raw)
    assert row.revoked_at is not None
    assert row.rotated_to_id is None

    with pytest.raises(AuthError):
        await auth_service.refresh_tokens(db, raw_refresh_token=raw)

    assert "user.refresh_token_reuse_detected" in await _actions(db)
