from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.refresh_token import RefreshToken
from app.core.phone import normalize_phone, normalized_phone_column
from app.core.security import (
    verify_password,
    create_access_token,
    generate_refresh_token,
    hash_token,
    refresh_token_expires_at,
)
from app.core.exceptions import AuthError
from app.schemas.auth import TokenResponse
from app.services.audit_service import log_action
from app.services import login_throttle
from app.core.token_revocation import revoke_user_tokens
from app.config import get_settings


async def login(
    db: AsyncSession,
    *,
    identifier: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    """Вход по email ИЛИ номеру телефона.

    Если в identifier есть «@» — ищем по email; иначе по телефону (последние 10
    цифр, формат хранения свободный). Ошибка всегда одинаковая, чтобы нельзя было
    отличить «нет такого аккаунта» от «неверный пароль» (защита от перебора).
    """
    ident = (identifier or "").strip()
    throttle_key = ident.lower()
    GENERIC_ERR = "Неверный логин или пароль"

    # Per-identifier backoff check — same generic error whether blocked or wrong creds
    if await login_throttle.check_blocked(throttle_key):
        raise AuthError(GENERIC_ERR)

    if "@" in ident:
        result = await db.execute(select(User).where(User.email == ident.lower()))
        user = result.scalar_one_or_none()
    else:
        norm = normalize_phone(ident)
        if len(norm) == 10:
            result = await db.execute(
                select(User).where(
                    User.phone.isnot(None),
                    normalized_phone_column(User.phone) == norm,
                )
            )
            user = result.scalars().first()
        else:
            user = None

    # Record failure for non-existent identifier too — prevents user enumeration via
    # differential blocking (attacker can't tell "no such account" from "wrong pw")
    if not user or not verify_password(password, user.hashed_password):
        await login_throttle.record_failure(throttle_key)
        raise AuthError(GENERIC_ERR)

    if user.is_archived:
        await login_throttle.record_failure(throttle_key)
        raise AuthError(GENERIC_ERR)
    if not user.is_active:
        await login_throttle.record_failure(throttle_key)
        raise AuthError(GENERIC_ERR)

    # Successful login — clear throttle state
    await login_throttle.reset(throttle_key)

    access_token = create_access_token(str(user.id), user.role.value, user.full_name)
    raw_refresh = generate_refresh_token()

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=refresh_token_expires_at(),
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    await log_action(
        db,
        action="user.login",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"identifier": ident},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)


async def _issue_tokens_for_user(
    db: AsyncSession,
    user: User,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    """Issue access+refresh tokens for a pre-authenticated user (SMS-code login)."""
    access_token = create_access_token(str(user.id), user.role.value, user.full_name)
    raw_refresh = generate_refresh_token()

    db.add(RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=refresh_token_expires_at(),
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    await log_action(
        db,
        action="user.login_sms",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details={"identifier": str(user.phone or user.email)},
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)


def _as_utc(value: datetime | None) -> datetime | None:
    """Драйверы/БД могут отдать naive datetime — считаем такие UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _load_usable_user(db: AsyncSession, user_id) -> User:
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or user.is_archived or not user.is_active:
        raise AuthError("Пользователь недоступен")
    return user


async def _issue_refresh_pair(
    db: AsyncSession,
    user: User,
    *,
    ip_address: str | None,
    user_agent: str | None,
    audit_details: dict | None = None,
) -> tuple[RefreshToken, TokenResponse]:
    """Выпустить новую пару access+refresh. Возвращает и ORM-объект нового
    refresh-токена — нужен вызывающему, чтобы связать его с предшественником."""
    access_token = create_access_token(str(user.id), user.role.value, user.full_name)
    new_raw_refresh = generate_refresh_token()

    new_token = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_raw_refresh),
        expires_at=refresh_token_expires_at(),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(new_token)
    # flush — чтобы у нового токена появился id (нужен для rotated_to_id)
    await db.flush()

    await log_action(
        db,
        action="user.token_refresh",
        actor_id=user.id,
        entity_type="user",
        entity_id=user.id,
        details=audit_details,
        ip_address=ip_address,
    )

    return new_token, TokenResponse(
        access_token=access_token, refresh_token=new_raw_refresh
    )


async def refresh_tokens(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> TokenResponse:
    token_hash = hash_token(raw_refresh_token)
    now = datetime.now(timezone.utc)
    grace_seconds = get_settings().refresh_rotation_grace_seconds

    # Reuse detection: ищем токен БЕЗ фильтра is_revoked. Отозванный токен может
    # прилететь по двум сценариям:
    #   1) штатная гонка — две вкладки/устройства обновились одновременно,
    #      проигравшая прислала уже ротированный токен на миллисекунды позже;
    #   2) атака — переигрывание украденного токена.
    # Отличаем по паре (revoked_at, rotated_to_id): при ротации проставлены оба,
    # при logout/logout_all — только revoked_at. Свежая ротация внутри grace-окна
    # трактуется как (1): просто выдаём новую пару, ничего не отзывая.
    # Всё остальное — как раньше: сносим ВСЮ refresh-цепочку юзера.
    stolen_result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    seen = stolen_result.scalar_one_or_none()
    if seen and seen.is_revoked:
        revoked_at = _as_utc(seen.revoked_at)
        is_parallel_refresh = (
            revoked_at is not None
            and seen.rotated_to_id is not None
            and (now - revoked_at).total_seconds() <= grace_seconds
        )

        if is_parallel_refresh:
            user = await _load_usable_user(db, seen.user_id)
            _, response = await _issue_refresh_pair(
                db,
                user,
                ip_address=ip_address,
                user_agent=user_agent,
                audit_details={"duplicate_within_grace": True},
            )
            return response

        await logout_all(db, user_id=seen.user_id)
        await log_action(
            db,
            action="user.refresh_token_reuse_detected",
            actor_id=seen.user_id,
            entity_type="user",
            entity_id=seen.user_id,
            details={"reason": "revoked token re-used — all sessions invalidated"},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await db.commit()
        raise AuthError("Refresh token недействителен или истёк")

    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712
            RefreshToken.expires_at > now,
        )
    )
    db_token = result.scalar_one_or_none()

    if not db_token:
        raise AuthError("Refresh token недействителен или истёк")

    user = await _load_usable_user(db, db_token.user_id)

    new_token, response = await _issue_refresh_pair(
        db,
        user,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    # Rotate: revoke old, link to successor
    db_token.is_revoked = True
    db_token.revoked_at = now
    db_token.rotated_to_id = new_token.id

    return response


async def logout(
    db: AsyncSession,
    *,
    raw_refresh_token: str,
    actor_id,
) -> None:
    token_hash = hash_token(raw_refresh_token)
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == actor_id,
        )
    )
    db_token = result.scalar_one_or_none()
    if db_token:
        db_token.is_revoked = True
        # revoked_at ставим, rotated_to_id — НЕТ: повтор такого токена должен
        # уходить в ветку «кража» даже сразу после выхода.
        db_token.revoked_at = datetime.now(timezone.utc)

    # Отозвать уже выпущенные access-токены (живут до 15 мин) — иначе разлогин
    # не отрезает украденный/активный токен до его естественного истечения.
    await revoke_user_tokens(str(actor_id))

    await log_action(
        db,
        action="user.logout",
        actor_id=actor_id,
        entity_type="user",
        entity_id=actor_id,
    )


async def logout_all(db: AsyncSession, *, user_id) -> None:
    """Revoke all refresh tokens for the user (e.g. on password change)."""
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.user_id == user_id,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
    )
    now = datetime.now(timezone.utc)
    for token in result.scalars().all():
        token.is_revoked = True
        # Как и в logout(): rotated_to_id не трогаем — это не ротация.
        token.revoked_at = now

    await revoke_user_tokens(str(user_id))
