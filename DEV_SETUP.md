# Локальный запуск стенда с нуля

Шаги, чтобы поднять весь стек BaltOIL на новой машине (Windows + Docker Desktop
или Linux/macOS + Docker). Прод поднимается иначе — см. `DEPLOY.md`.

> Файлы `.env`, `tls/`, `docker-compose.override.yml` **в git не уезжают**
> (см. `.gitignore`) — их нужно создать локально по этому документу.

---

## 0. Предусловия

- Docker + docker compose (Docker Desktop на Windows/macOS).
- `openssl` (есть в git-bash на Windows).
- Порты свободны: 80, 443, 8001–8006, 7880, 7881, 50000–50100/udp.

## 1. `.env` для всех сервисов

У 5 сервисов есть `.env.example` — копируем:

```bash
cp auth_service/.env.example         auth_service/.env
cp order_service/.env.example        order_service/.env
cp delivery_service/.env.example     delivery_service/.env
cp chat_service/.env.example         chat_service/.env
cp notification_service/.env.example notification_service/.env
```

### 1a. Починить notification_service/.env

В его `.env.example` поля `JWT_SECRET_KEY` и `INTERNAL_API_SECRET` **пустые** —
если оставить, JWT сломается, а inter-service вызовы вернут 403. Выставить
те же значения, что у остальных (dev-дефолты):

```
JWT_SECRET_KEY=change-me-to-a-very-long-random-secret
INTERNAL_API_SECRET=baltoil-internal-secret-2026
```

> **Инвариант:** `JWT_SECRET_KEY` и `INTERNAL_API_SECRET` должны быть
> ОДИНАКОВЫ во всех 6 сервисах, иначе токены/внутренние вызовы отвалятся.

### 1b. call_service/.env (шаблона нет — создать вручную)

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/baltoil_calls
REDIS_URL=redis://redis:6379/4
JWT_SECRET_KEY=change-me-to-a-very-long-random-secret
JWT_ALGORITHM=HS256
APP_ENV=development
APP_PORT=8006
ALLOWED_ORIGINS=https://localhost,http://localhost,http://localhost:8080
LIVEKIT_URL=ws://livekit:7880
LIVEKIT_PUBLIC_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=devsecret-at-least-32-chars-long-padding
CHAT_SERVICE_URL=http://chat_service:8004
INTERNAL_API_SECRET=baltoil-internal-secret-2026
```

> Звонки (LiveKit) локально не тестируем — ключи-заглушки только чтобы
> сервис стартовал.

> `DADATA_API_KEY` в `auth_service/.env` можно оставить пустым — тогда
> поиск по ИНН/БИК отключён (на форме регистрации просто не сработает
> автозаполнение). Для реального ключа — взять на dadata.ru.

## 2. Self-signed TLS (nginx без них не стартует)

```bash
mkdir -p tls
# git-bash на Windows: MSYS_NO_PATHCONV=1 не даёт манглить /CN=...
MSYS_NO_PATHCONV=1 openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout tls/key.pem -out tls/cert.pem -days 365 \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

## 3. CORS-override (фронт на https://localhost ходит к API на :8001–8006)

В `.env` у сервисов CORS = только `http://localhost:8080`. Локальный фронт
открывается по `https://localhost`, поэтому нужен override (gitignored):

Создать `docker-compose.override.yml`:

```yaml
services:
  auth_service:         { environment: { ALLOWED_ORIGINS: "https://localhost,http://localhost,http://localhost:8080" } }
  order_service:        { environment: { ALLOWED_ORIGINS: "https://localhost,http://localhost,http://localhost:8080" } }
  delivery_service:     { environment: { ALLOWED_ORIGINS: "https://localhost,http://localhost,http://localhost:8080" } }
  chat_service:         { environment: { ALLOWED_ORIGINS: "https://localhost,http://localhost,http://localhost:8080" } }
  notification_service: { environment: { ALLOWED_ORIGINS: "https://localhost,http://localhost,http://localhost:8080" } }
  call_service:         { environment: { ALLOWED_ORIGINS: "https://localhost,http://localhost,http://localhost:8080" } }
```

## 4. Поднять стек

```bash
docker compose up -d
docker compose ps -a   # все 10 контейнеров должны быть Up; postgres/redis — healthy
```

Миграции Alembic накатываются автоматически из `entrypoint.sh` каждого сервиса.
БД создаются скриптом `postgres-init/01-create-databases.sh` (нужен LF —
гарантируется `.gitattributes`).

Если какой-то backend в `Exited` — `docker compose logs <service> --tail=30`.

## 5. Тестовые данные

Dev-пользователи создаются авто при старте `auth_service` (bootstrap), если
БД пустая. Заявки/платежи — отдельным сидом:

```bash
docker compose exec -T order_service python /app/scripts/seed.py
# создаёт legal_entity, 10 заявок (ORD-2026-000001..010), 5 платежей
```

Документы (счёт/ТТН/УПД) генерятся по событиям заявки. Чтобы быстро получить
готовые PDF на сид-заявках — сгенерировать вручную через REST или python-сниппет
(см. историю; на проде генерятся сами при prepaid/DELIVERED/CLOSED).

## 6. Вход

Открыть `https://localhost`. Браузер ругнётся на self-signed cert →
**Advanced → Proceed**.

> **Важно:** AJAX идёт на `https://localhost:8001` (auth) и `:8002` (orders) —
> это ОТДЕЛЬНЫЕ порты, cert для каждого надо принять один раз. Открой
> `https://localhost:8001/health` и `https://localhost:8002/health` в новых
> вкладках, прими cert, потом возвращайся на `https://localhost`. Иначе
> логин «молча» падает (фронт показывает 401 на самом деле network error).

Dev-аккаунты (создаёт bootstrap при пустой БД):

| Роль | Email | Пароль |
|---|---|---|
| admin | `admin@baltoil.ru` | `Admin1234!` |
| manager | `manager@baltoil.ru` | `Manager1!` |
| driver | `driver@baltoil.ru` | `Driver11!` |
| client | `client@baltoil.ru` | `Client1!` |

Bootstrap-админ из `.env`: `admin@baltoil.biz` / `change-me-strong-password`.

### Сбросить login-throttle

После нескольких неудачных попыток email блокируется (anti-brute-force в Redis):

```bash
docker compose exec redis sh -c "redis-cli --scan --pattern '*login*' | xargs -r redis-cli del"
```

## 7. Сброс БД начисто

```bash
docker compose down -v   # -v удаляет volume postgres → миграции прогонятся заново
docker compose up -d
```

---

## Частые грабли

- **`/bin/bash^M: bad interpreter`** — CRLF в shell-скрипте. Лечится
  `.gitattributes` (eol=lf); если всё равно — `dos2unix <файл>`.
- **nginx 502 после `up -d --force-recreate <svc>`** — nginx закешировал
  старый IP. `docker compose restart frontend`.
- **`docker compose restart` не перечитывает `.env`** — нужен
  `up -d --force-recreate <svc>`.
- **notification_service 403 на отправку email** — рассинхрон
  `INTERNAL_API_SECRET` (см. п.1a).
- **PDF не генерится (`'super' object has no attribute 'transform'`)** —
  несовместимость weasyprint/pydyf; pin `pydyf<0.11` уже в requirements.
