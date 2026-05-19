# SPEC: Security & Performance Audit Fixes

> Цель: закрыть дыры, найденные в аудите 2026-05-19, **которые не требуют ротации секретов**. Ротация secrets/root/SSH вынесена в отдельный pre-prod hardening pass.

> Этот файл — для Sonnet. Каждый раздел = отдельный PR. Внутри раздела — последовательные изменения. Не смешивать PR’ы.

---

## PR 1 — Authentication & Rate Limiting

### 1.1. Доверять `X-Real-IP` от nginx

**Файл:** `auth_service/app/core/dependencies.py:70-77`

Заменить функцию `get_request_meta`:

```python
def _trusted_client_ip(request: Request) -> str:
    """Nginx sets X-Real-IP from $remote_addr (real client TCP peer).
    We trust it because backend services have no host port — only nginx can talk to them.
    Falls back to direct peer if header missing (e.g. local debugging)."""
    return request.headers.get("X-Real-IP") or (request.client.host if request.client else "0.0.0.0")


def get_request_meta(request: Request) -> dict:
    return {
        "ip_address": _trusted_client_ip(request),
        "user_agent": request.headers.get("User-Agent"),
    }
```

Экспортировать `_trusted_client_ip` (без подчёркивания, как `trusted_client_ip`) — он будет ключом для slowapi.

**Проверить:** все вызовы `get_request_meta` — они уже передают `ip_address` дальше, формат не меняется.

### 1.2. slowapi на Redis-storage + trusted IP

**Файл:** `auth_service/app/routers/auth.py`

```python
from app.config import get_settings
from app.core.dependencies import trusted_client_ip

settings_ = get_settings()
limiter = Limiter(
    key_func=trusted_client_ip,
    storage_uri=settings_.redis_url,
    strategy="fixed-window",
)
```

Добавить в `auth_service/.env.example` и `app/config.py`: поле `redis_url: str = "redis://redis:6379"`.

**Файл:** `auth_service/app/routers/users.py:12` — то же самое (Limiter с trusted IP + Redis storage).

В `app/main.py` повесить slowapi handler:
```python
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
app.state.limiter = limiter  # из общего модуля app/core/rate_limit.py
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

Чтобы не было двух экземпляров `Limiter`, вынести в `auth_service/app/core/rate_limit.py`:
```python
from slowapi import Limiter
from app.config import get_settings
from app.core.dependencies import trusted_client_ip

limiter = Limiter(
    key_func=trusted_client_ip,
    storage_uri=get_settings().redis_url,
    strategy="fixed-window",
)
```

И импортировать оттуда в обоих роутерах.

### 1.3. Конкретные лимиты

| Эндпоинт | Decorator | Обоснование |
|---|---|---|
| `POST /auth/login` | `@limiter.limit("30/minute")` | защита от spray с одного IP; per-email отдельно (1.4) |
| `POST /auth/register/individual` | `@limiter.limit("5/minute")` | регистрация — редкое событие |
| `POST /auth/register/company` | `@limiter.limit("5/minute")` | то же |
| `POST /auth/refresh` | `@limiter.limit("60/minute")` | живой клиент рефрешит раз в ~15 мин |

### 1.4. Per-email backoff на login

**Файл:** `auth_service/app/services/auth_service.py` (метод `login`)

Логика:
1. Перед `verify_password` прочитать счётчик `login_fail:<email_lower>` из Redis.
2. Если есть `block_until` для этого email и `now < block_until` → `AuthError("Слишком много попыток, попробуйте позже")` с **тем же текстом**, что и обычная ошибка пароля (анти-enumeration).
3. После `verify_password`:
   - успех → `DEL login_fail:<email_lower>` и `DEL login_block:<email_lower>`
   - провал → `INCR login_fail:<email_lower>` + `EXPIRE 3600`. По достижении порогов — выставить `block_until`:
     - 5 fails → block на 60s
     - 10 fails → block на 300s
     - 20 fails → block на 1800s
     - 30+ → block на 7200s

Реализация — отдельный модуль `auth_service/app/services/login_throttle.py`:

```python
import time
from typing import Optional
import redis.asyncio as aioredis
from app.config import get_settings

settings = get_settings()

_BACKOFF = [(5, 60), (10, 300), (20, 1800), (30, 7200)]
_FAIL_TTL = 3600


async def _redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def check_blocked(email: str) -> Optional[int]:
    """Returns seconds remaining if blocked, else None."""
    r = await _redis()
    try:
        until = await r.get(f"login_block:{email}")
        if until and float(until) > time.time():
            return int(float(until) - time.time())
        return None
    finally:
        await r.aclose()


async def record_failure(email: str) -> None:
    r = await _redis()
    try:
        n = await r.incr(f"login_fail:{email}")
        if n == 1:
            await r.expire(f"login_fail:{email}", _FAIL_TTL)
        for threshold, block_secs in _BACKOFF:
            if n >= threshold:
                await r.set(f"login_block:{email}", time.time() + block_secs, ex=block_secs + 60)
    finally:
        await r.aclose()


async def reset(email: str) -> None:
    r = await _redis()
    try:
        await r.delete(f"login_fail:{email}", f"login_block:{email}")
    finally:
        await r.aclose()
```

В `auth_service.login`:
- В начале: `email_norm = email.lower().strip(); if await check_blocked(email_norm): raise AuthError("Неверный email или пароль")` (общий текст!)
- При успехе: `await reset(email_norm)` после issue tokens
- При failure (плохой пароль ИЛИ юзера нет ИЛИ archived): `await record_failure(email_norm)`. **Записывать даже если юзера нет** — иначе атакующий сможет различать «существует» / «не существует» по тому, что один email блокируется а другой нет.

**Тесты (вручную):**
1. 4 неудачные попытки — `401`.
2. 5-я неудачная — `401`, и сразу 6-я подряд тоже `401` («Неверный email или пароль» — без раскрытия причины).
3. Подождать 65с — снова можно (одна попытка).
4. Успешный login после 3 фейлов — счётчик сбрасывается.

### 1.5. Per-user rate limit на отправку сообщений (WS)

**Файл:** `chat_service/app/services/message_service.py`, в начале `send_message`:

```python
async def _check_message_rate(actor_id: uuid.UUID, conv_id: uuid.UUID) -> None:
    """60 messages / min per (user, conversation). Raises ForbiddenError on exceed."""
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = f"msgrate:{actor_id}:{conv_id}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, 60)
        if n > 60:
            raise ForbiddenError("Слишком много сообщений, подождите минуту")
    finally:
        await r.aclose()
```

Вызвать после `_check_access(conv, actor)`. Если `ForbiddenError` — WS endpoint должен поймать и отправить JSON-ошибку (см. 1.7), не падать.

### 1.6. Per-IP rate limit на WS connect

**Файл:** `chat_service/app/routers/websocket.py`

В начале `websocket_endpoint`, **до** `websocket.accept()`:

```python
# Rate-limit WS connects per real IP — 10 connects / 60s
ip = websocket.headers.get("x-real-ip") or (websocket.client.host if websocket.client else "0.0.0.0")
r = aioredis.from_url(settings.redis_url, decode_responses=True)
try:
    key = f"wsconn:{ip}"
    n = await r.incr(key)
    if n == 1:
        await r.expire(key, 60)
    if n > 10:
        await websocket.close(code=4429)
        return
finally:
    await r.aclose()
```

(в идеале вынести в shared util, но один файл — ок для первой итерации)

### 1.7. WS обработка ошибок Rate-limit

**Файл:** `chat_service/app/routers/websocket.py:100-110`

В цикле приёма сообщений обернуть `send_message` в try/except `ForbiddenError`:

```python
try:
    async with AsyncSessionLocal() as db:
        msg = await send_message(db, conv_id, text, actor)
except ForbiddenError as e:
    await websocket.send_text(json.dumps({"error": str(e)}))
    continue
```

### 1.8. nginx rate-limit (фронт-линия)

**Файл:** `frontend/nginx.conf` — в начало http-блока (вверху файла, до server-блоков):

```nginx
limit_req_zone $binary_remote_addr zone=login_zone:10m rate=5r/s;
limit_req_zone $binary_remote_addr zone=register_zone:10m rate=1r/s;
limit_req_zone $binary_remote_addr zone=api_zone:10m rate=30r/s;
limit_conn_zone $binary_remote_addr zone=ws_conn_zone:10m;
```

В `location /api/auth/` добавить `limit_req zone=api_zone burst=60 nodelay;`. Для конкретных путей login/register нужны отдельные локейшны:

```nginx
location = /api/auth/api/v1/auth/login {
    limit_req zone=login_zone burst=10 nodelay;
    limit_req_status 429;
    proxy_pass http://auth_service:8001/api/v1/auth/login;
    # ...все proxy_set_header как в общем /api/auth/
}

location ~ ^/api/auth/api/v1/auth/register/ {
    limit_req zone=register_zone burst=3 nodelay;
    limit_req_status 429;
    proxy_pass http://auth_service:8001;
    # ...
}
```

Внутри `location /api/chat/` для WS-upgrade:
```nginx
limit_conn ws_conn_zone 10;
```

**Acceptance:**
- 60 быстрых POST на `/api/auth/api/v1/auth/login` с одного IP — последние получают `429` от nginx.
- 6 register-запросов за 3 секунды — последние `429`.
- 11-й WS-коннект с одного IP — закрывается с кодом 4429 на app-уровне (либо на уровне nginx — что сработает раньше).

---

## PR 2 — Lock down internal endpoints + audit

### 2.1. nginx — блокировать `/internal/*` через wildcard

**Файл:** `frontend/nginx.conf` — **до** существующих `location /api/<service>/`:

```nginx
# Internal service-to-service endpoints — never expose publicly.
# Backend services share docker network for these.
location ~ ^/api/[^/]+/(api/v[0-9]+/)?internal(/|$) {
    return 404;
}
```

**Acceptance:**
- `curl -sk https://host/api/auth/api/v1/internal/users-by-role?roles=admin -H "X-Internal-Secret: ..."` → `404` (без обращения к backend).
- `curl -sk https://host/api/chat/internal/conversations/<uuid>/system-message -H "X-Internal-Secret: ..." -d '{"text":"x"}'` → `404`.
- Внутри docker (`docker compose exec call_service curl http://chat_service:8004/internal/...`) — продолжает работать.

### 2.2. Audit log для `update_client_profile`

**Файл:** `auth_service/app/services/user_service.py:318-341`

После `for field, value in ...: setattr(...)` собрать diff и записать `log_action`:

```python
changed = {}
for field, value in data.model_dump(exclude_none=True).items():
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
    )

return profile
```

Расширить сигнатуру функции — принять `ip_address: str | None = None` и пробросить в `log_action`. Соответственно правка вызова в `users.py:114-123` — передать `ip_address=meta["ip_address"]`.

### 2.3. Сократить TTL access-токена

**Файл:** `auth_service/.env` (на сервере и в `.env.example`):

```
ACCESS_TOKEN_EXPIRE_MINUTES=15
```

(было 60)

Refresh остаётся 30 дней.

**Acceptance:** новый login → `decode(access).exp - iat == 900` (±). Refresh продолжает работать.

---

## PR 3 — Performance: Redis pool + N+1 + WS pubsub singleton

### 3.1. App-level Redis pool через FastAPI lifespan

**Файл:** `chat_service/app/main.py`

```python
import redis.asyncio as aioredis

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing db init ...
    app.state.redis = aioredis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=50,
    )
    try:
        yield
    finally:
        await app.state.redis.aclose()
```

Добавить dependency:
```python
# app/core/redis_dep.py
from fastapi import Request
import redis.asyncio as aioredis

def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis
```

В `send_message`, `post_system_message`, `create_conversation`, `_check_message_rate` — заменить `aioredis.from_url(...) ... await r.aclose()` на принимаемый параметр `redis: aioredis.Redis`. Роутеры передают из `Depends(get_redis)`.

То же самое в **call_service**, **notification_service**, **auth_service** (для login throttle).

### 3.2. WS — singleton pubsub listener на conv

**Файл:** `chat_service/app/routers/websocket.py`

Проблема: сейчас каждый WS-клиент держит отдельную Redis-подписку. На 1000 онлайн = 1000 TCP. Цель: одна подписка на `chat:{conv_id}` на процесс, фан-аут в памяти.

Структура:

```python
# Module-level state
_connections: dict[str, set[WebSocket]] = {}
_subscriptions: dict[str, asyncio.Task] = {}
_subscription_lock = asyncio.Lock()


async def _ensure_subscription(redis: aioredis.Redis, conv_key: str):
    """Start a process-level pubsub listener for this conv if none exists."""
    async with _subscription_lock:
        if conv_key in _subscriptions and not _subscriptions[conv_key].done():
            return
        _subscriptions[conv_key] = asyncio.create_task(_listen(redis, conv_key))


async def _listen(redis: aioredis.Redis, conv_key: str):
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"chat:{conv_key}")
    try:
        async for raw in pubsub.listen():
            if raw["type"] != "message":
                continue
            dead = []
            for ws in list(_connections.get(conv_key, ())):
                try:
                    await ws.send_text(raw["data"])
                except Exception:
                    dead.append(ws)
            for ws in dead:
                _connections[conv_key].discard(ws)
            if not _connections.get(conv_key):
                break
    finally:
        await pubsub.unsubscribe(f"chat:{conv_key}")
        await pubsub.aclose()
        _subscriptions.pop(conv_key, None)
```

В `websocket_endpoint`:
- убрать локальный `redis_listener` task
- использовать `app.state.redis` (через `websocket.app.state.redis`)
- после `_connections[conv_key].add(websocket)` вызвать `await _ensure_subscription(redis, conv_key)`
- в `finally` блоке: `_connections[conv_key].discard(websocket); if not _connections[conv_key]: _connections.pop(conv_key, None)` — подписка сама завершится, потому что listener видит `not _connections.get(conv_key)`

**Acceptance:**
- 50 одновременных WS в один conv → `docker exec ... redis-cli CLIENT LIST | wc -l` показывает ~1-2 подписки на этот conv, не 50.
- Отправка сообщения через REST/WS доходит до всех 50 коннектов.

### 3.3. Переписать `list_conversations` — unread в одном SQL

**Файл:** `chat_service/app/services/conversation_service.py:180-289`

Заменить «Запрос 3» (строки 252-271) на:

```python
from sqlalchemy import case, func

# Один SELECT: unread_count = COUNT(messages где created_at > p.last_read_at AND sender != actor)
unread_q = (
    select(
        Message.conversation_id,
        func.count(Message.id).label("unread"),
    )
    .join(
        ConversationParticipant,
        and_(
            ConversationParticipant.conversation_id == Message.conversation_id,
            ConversationParticipant.user_id == actor.id,
        ),
        isouter=True,
    )
    .where(
        Message.conversation_id.in_(conv_ids),
        Message.is_archived == False,  # noqa: E712
        Message.sender_id != actor.id,
        # last_read_at is NULL → всё считается непрочитанным
        (ConversationParticipant.last_read_at.is_(None))
        | (Message.created_at > ConversationParticipant.last_read_at),
    )
    .group_by(Message.conversation_id)
)
unread_res = await db.execute(unread_q)
unread_counts: dict[uuid.UUID, int] = {row.conversation_id: row.unread for row in unread_res}
# default 0 для конвов без сообщений
unread_counts = {cid: unread_counts.get(cid, 0) for cid in conv_ids}
```

И убрать петлю «Group by conv» в Python.

**Acceptance:**
- Юнит-тест (или manual): создать conv с 100 сообщениями от другого юзера, last_read_at в прошлом → unread_count = 100, и не отдельные 100 строк в Python.
- `EXPLAIN ANALYZE` запроса не должен брать > 50ms на 10k сообщений.

---

## PR 4 — Мелочёвка

### 4.1. Publish событие при delete/clear conversation

**Файл:** `chat_service/app/services/conversation_service.py:319-345`

В `delete_conversation` после успешного `await db.commit()`:

```python
try:
    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.publish(f"chat:{conv_id}", json.dumps({
            "event": "conversation_deleted",
            "conversation_id": str(conv_id),
        }))
    finally:
        await r.aclose()
except Exception:
    logger.exception("Failed to publish conversation_deleted event")
```

(после PR 3.1 — использовать `app.state.redis`.)

То же для `clear_conversation`: событие `"event": "conversation_cleared"`.

**Frontend:** в `connectWs`/обработчике входящих сообщений добавить:
```js
if (data.event === 'conversation_deleted') { /* закрыть открытый чат, обновить список */ }
if (data.event === 'conversation_cleared') { /* очистить msg-список UI */ }
```

### 4.2. Проверка URL-схемы и `rel="noopener"` в чате

**Файл:** `frontend/index.html` — в районе рендера документа в чате (поиск `meta.download_path`):

Заменить:
```js
<a href="${escHtml(meta.download_path || '#')}" target="_blank" ...>
```

на:
```js
<a href="${safeHttpUrl(meta.download_path)}" target="_blank" rel="noopener noreferrer" ...>
```

Добавить helper:
```js
function safeHttpUrl(u) {
  if (!u || typeof u !== 'string') return '#';
  const s = u.trim();
  // Allow only http(s) and same-origin paths
  if (/^https?:\/\//i.test(s) || s.startsWith('/')) return escHtml(s);
  return '#';
}
```

Применить ко всем `<a href="${...}" target="_blank">` в `index.html` где источник — серверные данные.

### 4.3. Убрать `--reload` из прод docker-compose

**Файл:** `docker-compose.yml` — все 6 backend сервисов:

```yaml
command: uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 2
```

(было `--reload`)

`--workers 2` — для CPU-bound нагрузки 2 ядра на сервис уже неплохо; можно начать с `--workers 1` если хост слабый.

**Внимание:** worktree/dev-сетап на той же машине может полагаться на `--reload`. Если нужен dev-режим — создать `docker-compose.dev.yml` с override:
```yaml
# docker-compose.dev.yml
services:
  auth_service:
    command: uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

И запускать dev как `docker compose -f docker-compose.yml -f docker-compose.dev.yml up`.

### 4.4. CORS — оставить только https

**Файлы:** `<service>/.env` (все 6) и `.env.example`:

```
ALLOWED_ORIGINS=https://5.42.118.110
```

(удалить `http://...:8080` и `http://...`)

Если frontend ходит на бэк через тот же origin (через nginx-proxy на 443) — CORS вообще не должен срабатывать. Проверить, что после правки фронт по-прежнему логинится.

---

## Не в SPEC (требует ручных действий)

- **Закоммитить или откатить uncommitted-изменения на `/opt/baltoil`** (включая новый `chat_service/app/routers/internal.py` — он не закоммичен). Сделать вручную: `cd /opt/baltoil && git add -A && git commit -m "..."` или `git stash` + сравнить с worktree.
- WS-токен в query-string → subprotocol — отложить, координированно с фронтом, отдельной задачей.

---

## Порядок выполнения

1. **PR 2** (nginx internal lockdown) — самый быстрый и закрывает реальную утечку. Минут 30.
2. **PR 1** (rate-limit + login backoff) — основная защита от brute-force.
3. **PR 3** (Redis pool + N+1) — перформанс, до того как трафик вырастет.
4. **PR 4** (мелочёвка) — фоном.
