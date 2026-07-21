"""FCM push adapter (HTTP v1 API).

Зеркало sms_service/email_service: fire-and-forget, ошибки логируются и
глотаются, глобальный kill-switch PUSH_ENABLED (по умолчанию false).

Требует сервис-аккаунт Firebase: JSON-файл монтируется в контейнер, путь —
в FCM_CREDENTIALS_FILE. project_id берётся из самого файла.

schedule_pushes() вызывается ТОЛЬКО после db.commit() — как schedule_emails().
"""
import asyncio
import json
import logging
import uuid

import httpx
from sqlalchemy import delete, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.device_token import DeviceToken
from app.models.notification import Notification

log = logging.getLogger(__name__)

_TIMEOUT = 10.0

# Лениво инициализируемые креды google-auth (sync-библиотека — освежаем токен
# в thread-пуле, чтобы не блокировать event loop).
_credentials = None
_project_id: str | None = None
_init_failed = False


def _load_credentials() -> bool:
    """Однократно загрузить сервис-аккаунт. False — пуши невозможны."""
    global _credentials, _project_id, _init_failed
    if _credentials is not None:
        return True
    if _init_failed:
        return False
    if not settings.fcm_credentials_file:
        log.info("push_service: FCM_CREDENTIALS_FILE не задан — пуши отключены")
        _init_failed = True
        return False
    try:
        from google.oauth2 import service_account

        _credentials = service_account.Credentials.from_service_account_file(
            settings.fcm_credentials_file,
            scopes=["https://www.googleapis.com/auth/firebase.messaging"],
        )
        with open(settings.fcm_credentials_file, encoding="utf-8") as f:
            _project_id = json.load(f)["project_id"]
        log.info("push_service: FCM credentials loaded, project=%s", _project_id)
        return True
    except Exception:
        log.exception("push_service: не удалось загрузить FCM credentials")
        _init_failed = True
        return False


def _fresh_access_token() -> str:
    """Sync: вернуть валидный OAuth2 access token (google-auth сам кэширует)."""
    import google.auth.transport.requests

    if not _credentials.valid:
        _credentials.refresh(google.auth.transport.requests.Request())
    return _credentials.token


async def _send_to_token(client: httpx.AsyncClient, access_token: str, fcm_token: str,
                         title: str, body: str, data: dict[str, str]) -> bool:
    """Отправить одно сообщение. False = токен мёртв, надо удалить из БД."""
    # Входящий звонок — data-only: без notification-блока фоновый обработчик
    # приложения (onBackgroundMessage) гарантированно запускается и показывает
    # нативный экран звонка (CallKit/ConnectionService). С notification-блоком
    # система показала бы обычную «шторку», а обработчик при убитом приложении
    # не сработал бы. Заголовок/текст кладём в data — их отрисует сам звонок.
    is_call = data.get("type") == "call_initiated"
    if is_call:
        call_data = {**data, "title": title, "body": body}
        message = {
            "message": {
                "token": fcm_token,
                "data": call_data,
                "android": {"priority": "high"},
                "apns": {
                    "headers": {"apns-priority": "10", "apns-push-type": "voip"},
                    "payload": {"aps": {"content-available": 1}},
                },
            }
        }
    else:
        message = {
            "message": {
                "token": fcm_token,
                "notification": {"title": title, "body": body},
                # data-полезная нагрузка: тип/сущность для навигации по тапу
                "data": data,
                "android": {"priority": "high"},
                "apns": {"headers": {"apns-priority": "10"}},
            }
        }
    url = f"https://fcm.googleapis.com/v1/projects/{_project_id}/messages:send"
    try:
        resp = await client.post(
            url, json=message,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code == 200:
            return True
        # 404 UNREGISTERED / 400 INVALID_ARGUMENT — устройство удалило приложение
        # или токен протух: чистим, чтобы не долбить FCM зря.
        if resp.status_code in (400, 404):
            log.info("push_service: dead token (HTTP %s), удаляем", resp.status_code)
            return False
        log.error("push_service: FCM HTTP %s: %s", resp.status_code, resp.text[:200])
        return True  # временная ошибка — токен не трогаем
    except Exception:
        log.exception("push_service: ошибка отправки FCM")
        return True


async def _push_one(n: Notification, extra_data: dict[str, str] | None = None) -> None:
    """Отправить пуш по одному уведомлению на все устройства получателя."""
    if not settings.push_enabled:
        log.debug("push_service: PUSH_ENABLED=false — skipped (user=%s)", n.user_id)
        return
    if not _load_credentials():
        return

    try:
        async with AsyncSessionLocal() as db:
            tokens = (
                await db.execute(
                    select(DeviceToken).where(DeviceToken.user_id == n.user_id)
                )
            ).scalars().all()
            if not tokens:
                return

            access_token = await asyncio.to_thread(_fresh_access_token)
            data = {
                "type": n.type.value,
                "entity_type": n.entity_type or "",
                "entity_id": str(n.entity_id) if n.entity_id else "",
                "notification_id": str(n.id) if n.id else "",
                **{k: str(v) for k, v in (extra_data or {}).items() if v},
            }
            dead: list[uuid.UUID] = []
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                for t in tokens:
                    ok = await _send_to_token(client, access_token, t.token, n.title, n.body, data)
                    if not ok:
                        dead.append(t.id)
            if dead:
                await db.execute(delete(DeviceToken).where(DeviceToken.id.in_(dead)))
                await db.commit()
    except Exception:
        log.exception("push_service: unexpected error for user=%s", n.user_id)


def schedule_pushes(
    notifications: list[Notification],
    extra_data: dict[str, str] | None = None,
) -> None:
    """Запланировать пуши для уже закоммиченных уведомлений.

    Как schedule_emails: вызывать ТОЛЬКО после db.commit(), пока сессия ещё
    открыта. Снимаем транзиентные копии полей — фоновая таска не должна
    трогать ORM-объект после закрытия сессии.

    extra_data — дополнительные data-поля FCM (правки 2026-07-21): для
    call_initiated это room_name/initiated_by_name, чтобы нативный экран
    входящего звонка показал имя и комнату без запроса к API.
    """
    if not settings.push_enabled:
        return
    for n in notifications:
        snapshot = Notification(
            id=n.id,
            user_id=n.user_id,
            type=n.type,
            title=n.title,
            body=n.body,
            entity_type=n.entity_type,
            entity_id=n.entity_id,
        )
        asyncio.create_task(_push_one(snapshot, extra_data))
