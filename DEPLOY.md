# Deploy / Server topology

## Канонический путь

**Прод сервер:** `5.42.118.110` (`msk-1-vm-53pm`)
**Путь к проекту:** `/opt/baltoil/` — **единственное** место, откуда поднимается `docker compose`.

Любые pull / docker compose команды выполняются строго отсюда:

```bash
ssh root@5.42.118.110
cd /opt/baltoil
git pull
```

Старый клон `/root/BaltOIL/` удалён 2026-05-23 (см. ниже). Не воссоздавать.

## Стандартный деплой

```bash
cd /opt/baltoil
git pull --ff-only origin master

# Если меняли .env какого-то сервиса — пересоздать контейнер (см. ниже про gotcha).
# Если только код — достаточно restart, так как код подключён через bind mount.

# Миграции (idempotent, можно дёргать всегда):
docker compose exec -T auth_service     alembic upgrade head
docker compose exec -T order_service    alembic upgrade head
docker compose exec -T chat_service     alembic upgrade head
docker compose exec -T delivery_service alembic upgrade head

# Перезапуск (для подхвата нового кода без пересборки образа):
docker compose restart <service_name>
```

## Gotchas

### 1. `docker compose restart` НЕ перечитывает .env

`restart` берёт существующий контейнер со всеми его уже-зафиксированными env vars. Если поменяли `.env` (например, добавили `DADATA_API_KEY`) — нужен **`up -d --force-recreate`**, иначе переменная не появится внутри:

```bash
docker compose up -d --force-recreate --no-deps <service_name>
```

### 2. Bind mounts фиксируются при создании контейнера

`docker-compose.yml` использует относительные пути (`./auth_service:/app`). Path резолвится в **абсолютный** в момент создания контейнера. Если compose запускался из `/root/BaltOIL/`, контейнер пожизненно биндит `/root/BaltOIL/auth_service` — даже после `git pull` в `/opt/baltoil/` изменения НЕ видны внутри контейнера.

Проверить, откуда биндится контейнер:
```bash
docker inspect baltoil-<svc>-1 --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{println}}{{end}}'
```

Если видишь `/root/BaltOIL/...` — пересоздай контейнер из `/opt/baltoil`:
```bash
cd /opt/baltoil
docker compose up -d --force-recreate --no-deps <service_name>
```

### 3. Миграции обязаны быть идемпотентными

Используем `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` и т.п. — допускается повторный `alembic upgrade head` без эффекта. Это избавляет от ручной сверки «применено ли уже» при rollback и параллельных деплоях.

### 4. nginx и runtime-резолв upstream'ов (фикс 2026-05-23)

До 2026-05-23 в `frontend/nginx.conf` все `proxy_pass` использовали имя контейнера напрямую (`proxy_pass http://auth_service:8001`). nginx резолвит такие имена **один раз при загрузке конфига** и кэширует IP навсегда. После `docker compose up -d --force-recreate <svc>` контейнер получает новый IP из подсети — nginx продолжает стучаться на старый и отдаёт `502 Bad Gateway` пока его не перезапустят.

Симптом на фронте: запросы к `/api/.../...` валятся с `502`, в логах nginx — `connect() failed (111: Connection refused) while connecting to upstream: "http://172.18.0.<old_ip>:..."`.

**Фикс уже в конфиге**: вверху `http`-контекста стоит `resolver 127.0.0.11 valid=10s ipv6=off;` (это docker embedded DNS), а в каждом `location` upstream задан через переменную:

```nginx
set $auth_upstream auth_service:8001;
proxy_pass http://$auth_upstream;
```

С переменной nginx **обязан** иметь `resolver` и резолвит на каждый запрос с TTL из `valid=`. После `force-recreate` любого backend-контейнера фронт сам подхватит новый IP в течение ~10 секунд — перезапускать `frontend` ради этого не нужно.

Если когда-нибудь надо добавить новый upstream — обязательно через переменную, иначе вернётся старый баг. Прямой `proxy_pass http://имя:порт` без `set $...` — запрещён.

**Подводный камень №1 (2026-05-25):** `set $upstream ...` обязан стоять **до** `rewrite ... break`. `break` останавливает все последующие директивы rewrite-модуля в этом location, а `set` — это тоже rewrite-модуль. Если порядок обратный — переменная остаётся пустой, `proxy_pass http://` → `[error] invalid URL prefix in "http://"` → 500 на всё, что проходит через этот location. В каждом `location`-блоке `set` идёт первым.

**Подводный камень №2 (2026-05-25):** Сам `nginx.conf` подмонтирован **как файл, не директория** (`./frontend/nginx.conf:/etc/nginx/conf.d/default.conf`). Bind-mount файла привязан к inode. `git pull` переписывает файл через atomic rename → новый inode на диске, контейнер всё ещё видит старый. `docker exec frontend nginx -s reload` перечитает то же старое содержимое и ничего не изменится.

Когда правится **сам nginx.conf** — обязательно `docker compose up -d --force-recreate --no-deps frontend` после `git pull`. Не `restart`, не `reload`. Это переустановит mount на актуальный inode. (Изменения только в JS/HTML внутри `frontend/` не задеты — там примонтирована директория, новый inode подхватывается.)

## История переезда (2026-05-23)

- До 2026-05-23 на сервере жили **две** копии репо: `/root/BaltOIL/` (legacy, откуда стартовал compose) и `/opt/baltoil/` (новая каноническая). Часть контейнеров (`order_service`, `chat_service`) была привязана к `/root/BaltOIL/` через bind-mount, пока остальные уже работали из `/opt/baltoil/`.
- 2026-05-23 во время Деплоя 2 спринта 2026-06 это всплыло: миграция `0006_legal_entity_okpo.py` не подхватилась, потому что файл лежал в `/opt/baltoil/`, а контейнер видел `/root/BaltOIL/`.
- Все контейнеры пересозданы через `docker compose up -d --force-recreate` из `/opt/baltoil/`, директория `/root/BaltOIL/` удалена.

## Untracked на сервере

Эти файлы есть только на проде, в git их нет — **не трогать при cleanup**:
- `/opt/baltoil/.env` (если используется) и `/opt/baltoil/<service>/.env` — секреты
- `/opt/baltoil/tls/` — TLS-сертификаты для nginx
- `/opt/baltoil/backups/` — дампы БД (см. `docs/BACKUP.md`)
