# BaltOIL — План работ: Этап 0 + Этап 1

> Этот документ — пошаговая спецификация для исполнителя (Sonnet).
> Каждый шаг содержит: цель, файлы, реализацию, критерии приёмки.
> **Шаги выполнять строго по порядку**, после каждого подэтапа коммит с понятным сообщением.
> **При любой неоднозначности — остановись и спроси у пользователя**, не додумывай.

---

## Глобальные правила исполнения

1. **Все изменения схемы БД — только через Alembic.** Никаких ручных `ALTER TABLE` на проде. Если найдёшь расхождение схемы с моделями — отдельная миграция, не «фикс».
2. **Не трогать прод-БД напрямую.** Все эксперименты на локальной dev-БД через `docker compose`.
3. **Никаких новых фич сверх описанного.** Если по ходу видишь нужное улучшение — записать в `TODO.md` отдельным пунктом, не вписывать в текущую задачу.
4. **Коммиты атомарные:** один логический шаг = один коммит. Сообщение в формате `feat:` / `fix:` / `chore:` / `refactor:`. Описывает *зачем*, не *что*.
5. **CLAUDE.md в `.gitignore`** — не коммитим.
6. **При работе с прод-данными во время миграции:** сначала бэкап, потом миграция, потом smoke-тест. Откат через `alembic downgrade -1`.
7. **Перед стартом каждого нового шага** — прочитать соответствующие модели и роутеры **актуальной версии**, а не полагаться на пути из этого SPEC.md (структура может уехать). Пути ниже — ориентиры, не догма.

---

## Контекст проекта (что есть на момент написания SPEC)

- **5 микросервисов:** `auth_service`, `order_service`, `delivery_service`, `chat_service`, `notification_service`
- **Один PostgreSQL** с несколькими БД (`baltoil_auth`, `baltoil_orders`, ...), инициализируется через `postgres-init/`
- **Redis** для pub/sub уведомлений и WebSocket
- **nginx-фронт** + React frontend
- **Alembic:** инициализирован (env.py + script.py.mako) в `auth_service` и `delivery_service`, **миграций нет**. В `order_service` и `chat_service` Alembic отсутствует.
- **Платежи:** в `order_service/app/models/payment.py` уже есть модель и роутер `payments.py`. На это опираемся, расширяем.
- **Деплой:** ручной `git pull && docker compose restart` на `5.42.118.110`
- **Прод-БД пустая в плане клиентов** — миграции можно катать без боязни data loss, но всё равно с бэкапом

---

# ЭТАП 0 — Фундамент

## Шаг 0.1. Alembic во всех сервисах

**Цель:** все 4 БД (auth/orders/delivery/chat) управляются миграциями. На чистой БД `alembic upgrade head` поднимает рабочую схему.

**Файлы:**
- `auth_service/alembic/versions/0001_baseline.py` (новый)
- `delivery_service/alembic/versions/0001_baseline.py` (новый)
- `order_service/alembic.ini` (новый)
- `order_service/alembic/env.py` (новый, по образцу auth_service)
- `order_service/alembic/script.py.mako` (новый)
- `order_service/alembic/versions/0001_baseline.py` (новый)
- `chat_service/alembic.ini` (новый)
- `chat_service/alembic/env.py` (новый)
- `chat_service/alembic/script.py.mako` (новый)
- `chat_service/alembic/versions/0001_baseline.py` (новый)
- `*/entrypoint.sh` (новый, см. ниже)
- `docker-compose.yml` (правка команд запуска)

**Реализация:**

1. Для `order_service` и `chat_service`:
   - `alembic init alembic` внутри контейнера
   - В `env.py` подключить `Base.metadata` из `app/models` (импорт всех модулей моделей, чтобы autogenerate их видел)
   - DB URL берётся из переменной окружения (как в auth_service), не хардкод
2. Для каждого сервиса:
   - `alembic revision --autogenerate -m "baseline"` — генерирует initial-миграцию
   - **Внимательно вычитать diff** перед коммитом: убрать ошибочные `op.drop_*` (autogenerate видит не все типы), проверить enum-значения (особенно `OrderStatus` — должны включать `ASSIGNED` как legacy), добавить недостающие индексы
3. Создать `entrypoint.sh` в каждом сервисе:
   ```bash
   #!/bin/sh
   set -e
   alembic upgrade head
   exec "$@"
   ```
4. В `docker-compose.yml` для каждого сервиса:
   - `entrypoint: ["sh", "/app/entrypoint.sh"]`
   - `command: uvicorn app.main:app --host 0.0.0.0 --port XXXX --reload` (остаётся как было)
5. **На проде:** после деплоя — `alembic stamp head` в каждой БД (помечает текущее состояние как baseline без выполнения миграции). **Без `upgrade`** — схема уже соответствует моделям.

**Критерии приёмки:**
- [ ] `docker compose down -v && docker compose up` на чистом окружении: все 4 БД создаются с нуля, миграции применяются, сервисы поднимаются без ошибок
- [ ] `alembic current` в каждом сервисе показывает `0001_baseline (head)`
- [ ] `alembic downgrade base && alembic upgrade head` работает чисто (можно вверх-вниз без ошибок)

**Коммит:** `feat: add Alembic migrations to all services with baseline`

---

## Шаг 0.2. Локальные бэкапы БД + заглушка для облачной синхронизации

**Цель:** дважды в сутки автоматический бэкап всех БД в `/var/backups/baltoil/`, ротация 14 дней, готовый код для облачной отгрузки (включается через `.env`, по умолчанию выключен).

**Файлы:**
- `scripts/backup_db.sh` (новый)
- `scripts/cleanup_backups.sh` (новый)
- `scripts/sync_backups_to_cloud.sh` (новый — заглушка, активируется через env)
- `scripts/restore_db.sh` (новый)
- `scripts/backup.env.example` (новый)
- `docs/BACKUP.md` (новый)
- `crontab.example` (новый — для документации)

**Реализация:**

### `scripts/backup_db.sh`
```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/baltoil}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATABASES=("baltoil_auth" "baltoil_orders" "baltoil_delivery" "baltoil_chat")

mkdir -p "$BACKUP_DIR"

for DB in "${DATABASES[@]}"; do
  FILE="$BACKUP_DIR/${DB}_${TIMESTAMP}.sql.gz"
  docker exec baltoil-postgres-1 pg_dump -U postgres "$DB" | gzip > "$FILE"
  echo "[$(date -Iseconds)] Backed up $DB to $FILE"
done

# Trigger cloud sync (no-op if not configured)
if [ -x "$(dirname "$0")/sync_backups_to_cloud.sh" ]; then
  "$(dirname "$0")/sync_backups_to_cloud.sh" || echo "[WARN] cloud sync failed (non-fatal)"
fi
```

### `scripts/cleanup_backups.sh`
```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-/var/backups/baltoil}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[$(date -Iseconds)] Cleaned backups older than $RETENTION_DAYS days"
```

### `scripts/sync_backups_to_cloud.sh` — ЗАГЛУШКА с реальной реализацией
```bash
#!/bin/bash
# Cloud sync: uploads /var/backups/baltoil/ to S3-compatible storage.
# Activates only when BACKUP_CLOUD_PROVIDER is set in scripts/backup.env.
set -euo pipefail

ENV_FILE="$(dirname "$0")/backup.env"
if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

if [ -z "${BACKUP_CLOUD_PROVIDER:-}" ]; then
  echo "[$(date -Iseconds)] Cloud sync skipped: BACKUP_CLOUD_PROVIDER not set"
  exit 0
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/baltoil}"

case "$BACKUP_CLOUD_PROVIDER" in
  s3|yandex|selectel)
    # Uses aws CLI with custom endpoint (works for any S3-compatible storage)
    AWS_ACCESS_KEY_ID="$BACKUP_CLOUD_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$BACKUP_CLOUD_SECRET_KEY" \
    aws s3 sync "$BACKUP_DIR" "s3://${BACKUP_CLOUD_BUCKET}/baltoil/" \
      --endpoint-url "$BACKUP_CLOUD_ENDPOINT" \
      --exclude "*" --include "*.sql.gz"
    echo "[$(date -Iseconds)] Cloud sync OK -> $BACKUP_CLOUD_PROVIDER"
    ;;
  *)
    echo "[ERROR] Unknown BACKUP_CLOUD_PROVIDER: $BACKUP_CLOUD_PROVIDER"
    exit 1
    ;;
esac
```

### `scripts/backup.env.example`
```bash
# Copy to scripts/backup.env and fill when ready to enable cloud sync.
# Leave BACKUP_CLOUD_PROVIDER empty to keep cloud sync disabled (local backups still run).

BACKUP_CLOUD_PROVIDER=        # s3 | yandex | selectel | (empty = disabled)
BACKUP_CLOUD_BUCKET=
BACKUP_CLOUD_ENDPOINT=        # https://storage.yandexcloud.net for Yandex
BACKUP_CLOUD_ACCESS_KEY=
BACKUP_CLOUD_SECRET_KEY=
```

### `scripts/restore_db.sh`
```bash
#!/bin/bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 <db_name> <backup_file.sql.gz>"
  exit 1
fi

DB="$1"
FILE="$2"

if [ ! -f "$FILE" ]; then
  echo "Backup file not found: $FILE"
  exit 1
fi

echo "[!] About to restore $DB from $FILE"
echo "[!] This will DROP and recreate $DB. Continue? (yes/no)"
read -r CONFIRM
[ "$CONFIRM" = "yes" ] || exit 1

docker exec baltoil-postgres-1 psql -U postgres -c "DROP DATABASE IF EXISTS ${DB};"
docker exec baltoil-postgres-1 psql -U postgres -c "CREATE DATABASE ${DB};"
gunzip -c "$FILE" | docker exec -i baltoil-postgres-1 psql -U postgres "$DB"
echo "[OK] Restored $DB from $FILE"
```

### `crontab.example`
```cron
# BaltOIL backups — install via: crontab -u root crontab.example
0 4,16 * * * /opt/baltoil/scripts/backup_db.sh >> /var/log/baltoil-backup.log 2>&1
30 5 * * * /opt/baltoil/scripts/cleanup_backups.sh >> /var/log/baltoil-backup.log 2>&1
```

### `docs/BACKUP.md`
Документировать:
- Где лежат бэкапы (`/var/backups/baltoil/`)
- Как настроить cron на проде
- Как включить облачную синхронизацию: скопировать `backup.env.example` → `backup.env`, заполнить, дать `chmod 600`
- Как восстановить БД: пример с `restore_db.sh`
- Контрольный список restore drill (см. шаг 0.4)

**Критерии приёмки:**
- [ ] На dev: `./scripts/backup_db.sh` создаёт 4 файла `*.sql.gz` в `/var/backups/baltoil/`
- [ ] Без `backup.env` cloud sync пишет «skipped» и выходит с кодом 0
- [ ] `./scripts/restore_db.sh baltoil_orders /var/backups/baltoil/baltoil_orders_*.sql.gz` восстанавливает БД (после подтверждения)
- [ ] `./scripts/cleanup_backups.sh` с искусственно подменённой mtime удаляет старые файлы
- [ ] `docs/BACKUP.md` содержит инструкцию которую может выполнить человек, который видит проект впервые
- [ ] **На проде:** crontab установлен, `/var/log/baltoil-backup.log` пишется

**Коммит:** `feat: automated database backups with cloud sync stub`

---

## Шаг 0.3. Seed-данные для разработки

**Цель:** `make seed` на dev-окружении наполняет БД реалистичными тестовыми данными. Запрещено в `APP_ENV=production`.

**Файлы:**
- `scripts/seed.py` (новый)
- `Makefile` (новый или дополнить)
- `docs/DEV_SETUP.md` (новый)

**Реализация:**

### `scripts/seed.py`
- В начале: `assert os.environ.get("APP_ENV") != "production", "seed.py is FORBIDDEN on production"`
- Использует SQLAlchemy-сессии каждого сервиса напрямую (не HTTP API — проще, надёжнее, не зависит от того что сервисы подняты)
- Создаёт:
  - **Пользователи:**
    - 1 admin: `admin@baltoil.test` / `admin123`
    - 2 manager: `manager1@baltoil.test`, `manager2@baltoil.test`
    - 2 driver: `driver1@baltoil.test`, `driver2@baltoil.test`
    - 5 client с разными типами оплаты (по умолчанию): `prepaid@`, `ondelivery@`, `tradecredit@`, `postpaid@`, `mixed@`
    - Все пароли: `password123`
  - **Топлива:** ДТ, АИ-92, АИ-95, АИ-98 с ценами
  - **Машины:** 2 машины с приписанными водителями
  - **Заявки (10 шт.):**
    - 2 в NEW
    - 2 в IN_PROGRESS
    - 1 в IN_TRANSIT
    - 2 в DELIVERED (одна полностью оплачена, одна — ожидает оплаты)
    - 1 в PARTIALLY_DELIVERED (с переплатой — клиент оплатил по плану, доставлено меньше)
    - 1 в CLOSED (полностью оплачена, ТТН/УПД сгенерированы)
    - 1 в REJECTED
  - **Платежи:** к каждой заявке привязаны соответствующие записи в `payments`
  - **Чат:** 2 чата (client-manager) с историей сообщений
- **Идемпотентность:** перед началом — `TRUNCATE` всех таблиц ИЛИ `DROP DATABASE && CREATE DATABASE && alembic upgrade head` (второй вариант надёжнее)

### `Makefile`
```makefile
.PHONY: seed seed-fresh

seed:
	@echo "Running seed (APP_ENV=$$APP_ENV)..."
	docker compose exec auth_service python /app/../scripts/seed.py

seed-fresh:
	@echo "Wiping and reseeding..."
	docker compose down -v
	docker compose up -d
	sleep 5
	$(MAKE) seed
```

### `docs/DEV_SETUP.md`
- Как поднять окружение с нуля
- Как запустить seed
- Логины тестовых пользователей
- Как сбросить данные

**Критерии приёмки:**
- [ ] На свежем окружении: `docker compose up -d` → `make seed` → можно залогиниться под `admin@baltoil.test` / `admin123` и увидеть 10 заявок в разных статусах
- [ ] При `APP_ENV=production` скрипт падает с понятной ошибкой и **не делает ничего**
- [ ] Повторный запуск `make seed-fresh` даёт идентичный результат

**Коммит:** `chore: add seed script and Makefile for dev data setup`

---

## Шаг 0.4. Restore drill

**Цель:** проверить, что бэкапы можно восстановить за разумное время.

**Реализация:**
1. На dev-машине (или временный docker контейнер): развернуть свежую копию docker-compose
2. Скачать актуальный бэкап с прода
3. Выполнить `./scripts/restore_db.sh` для каждой БД
4. Поднять фронт, проверить логин и работу основных страниц
5. **Записать в `docs/BACKUP.md`:**
   - Дата проведения drill
   - Время от начала до работающей системы
   - Найденные проблемы и их фиксы

**Критерии приёмки:**
- [ ] `docs/BACKUP.md` содержит секцию «## Restore drill log» с записью о проведённой проверке
- [ ] Время восстановления ≤ 30 минут от чистой машины до залогиненного админа
- [ ] Если что-то не сработало — отдельный коммит с фиксом, и drill повторён

**Коммит:** `docs: record restore drill results`

---

# ЭТАП 1 — Оплаты и документы

## Шаг 1.1. Расширение модели данных

**Цель:** модели в `order_service` поддерживают полный жизненный цикл оплат и документов.

**Файлы:**
- `order_service/app/models/order.py` (правка)
- `order_service/app/models/payment.py` (проверить/дополнить)
- `order_service/app/models/legal_entity.py` (новый)
- `order_service/app/models/document.py` (новый)
- `order_service/app/models/__init__.py` (добавить экспорты)
- `order_service/alembic/versions/0002_payments_documents_legal_entity.py` (новый, через autogenerate + ручная вычитка)

**Изменения схемы:**

### `orders` (правка)
- `payment_type` — enum: `prepaid`, `on_delivery`, `trade_credit`, `postpaid`. Default: `on_delivery`. **Backfill для существующих заявок:** `postpaid` (как «безопасный» — никто не блокирует существующие в IN_PROGRESS заявки).
- `expected_amount` — Numeric(12,2), nullable. Плановая сумма (объём × цена в момент создания).
- `final_amount` — Numeric(12,2), nullable. Фактическая сумма (после DELIVERED, на основе фактического объёма).
- `trade_credit_contract_signed` — Boolean, default false.

### `payments` (проверить, дополнить если нет)
- `id, order_id, amount, payment_date, payment_method (enum: cash/bank_transfer/card/other), recorded_by_id, note, created_at`
- Связь many-to-one с `orders`

### `legal_entities` (новая таблица)
```
id            int PK
name          str
inn           str
kpp           str (nullable)
ogrn          str
bank_name     str
bank_account  str
correspondent_account str
bik           str
legal_address str
postal_address str (nullable)
director_name str
phone         str (nullable)
email         str (nullable)
effective_from timestamptz NOT NULL
effective_to   timestamptz (nullable; null = active)
is_current    bool (denormalized, поддерживается триггером или в коде)
created_at    timestamptz
```
**Инвариант:** в любой момент только одна запись с `is_current=true` и `effective_to IS NULL`.

### `documents` (новая таблица)
```
id                      int PK
order_id                int FK -> orders
type                    enum (invoice_preliminary, invoice_final, upd, ttn, quality_cert)
file_path               str — относительный путь от document storage root
legal_entity_snapshot   jsonb — копия реквизитов на момент генерации
metadata                jsonb (nullable) — сумма, объём и т.п. для быстрой отдачи без открытия PDF
generated_at            timestamptz
generated_by_id         int (nullable) — null если сгенерировано системой
sent_to_client_at       timestamptz (nullable) — заполняется при первом скачивании клиентом
sent_by_id              int (nullable) — менеджер, отправивший в чат
created_at              timestamptz
```
Индекс: `(order_id, type)`.

**Реализация:**
1. Написать модели
2. `alembic revision --autogenerate -m "payments_documents_legal_entity"`
3. **Вычитать миграцию вручную**, добавить:
   - `op.execute("UPDATE orders SET payment_type = 'postpaid' WHERE payment_type IS NULL")` после `add_column`
   - Создание индексов
4. `alembic upgrade head` на dev, проверить
5. `alembic downgrade -1 && alembic upgrade head` — должно отработать чисто

**Критерии приёмки:**
- [ ] Миграция применяется на dev-БД с seed-данными без ошибок
- [ ] Downgrade работает чисто
- [ ] Все существующие заявки получили `payment_type='postpaid'`
- [ ] Seed-скрипт обновлён: теперь создаёт `legal_entity` (одну текущую) и создаёт заявки с разными `payment_type`

**Коммит:** `feat(orders): payment types, legal entity, document tables`

---

## Шаг 1.2. Логика расчёта `payment_status`

**Цель:** `payment_status` корректно отражает соотношение оплат и финальной суммы.

**Файлы:**
- `order_service/app/services/payment_service.py` (новый или дополнить)
- `order_service/app/models/order.py` (если payment_status поле — оставляем как cached column)
- `order_service/tests/test_payment_status.py` (новый)

**Реализация:**

```python
# order_service/app/services/payment_service.py

from decimal import Decimal
from app.models.order import Order, PaymentStatus

def compute_payment_status(order: Order, total_paid: Decimal) -> PaymentStatus:
    """Compute payment status from order amount and total paid."""
    # Use final_amount if order is delivered; otherwise expected_amount
    target = order.final_amount if order.final_amount is not None else order.expected_amount
    if target is None or target == 0:
        return PaymentStatus.UNPAID if total_paid == 0 else PaymentStatus.OVERPAID

    if total_paid == 0:
        return PaymentStatus.UNPAID
    if total_paid < target:
        return PaymentStatus.PARTIALLY_PAID
    if total_paid == target:
        return PaymentStatus.PAID
    return PaymentStatus.OVERPAID

def recompute_and_save(db, order_id: int):
    """Recompute payment_status for order and persist."""
    order = db.query(Order).get(order_id)
    total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.order_id == order_id
    ).scalar()
    order.payment_status = compute_payment_status(order, total)
    db.commit()
```

Вызывать `recompute_and_save` после:
- Создания/изменения/удаления `Payment`
- Установки `Order.final_amount` (при переходе в DELIVERED/PARTIALLY_DELIVERED)

**Добавить enum value:** `OVERPAID` в `PaymentStatus` (если ещё нет).

**Критерии приёмки:**
- [ ] Юнит-тесты `tests/test_payment_status.py` покрывают все 4 ветки (unpaid, partially_paid, paid, overpaid) + кейсы с `final_amount=None`
- [ ] Создание Payment через API триггерит пересчёт (есть тест)
- [ ] Удаление Payment через API триггерит пересчёт

**Коммит:** `feat(orders): payment_status computation with overpaid state`

---

## Шаг 1.3. Валидация перехода в CLOSED

**Цель:** заявку нельзя закрыть, пока оплата не получена (с исключением для trade_credit).

**Файлы:**
- `order_service/app/services/order_status_service.py` (где state machine)
- `order_service/app/routers/orders.py` (если валидация там)
- `frontend/src/...` (UI: tooltip на disabled кнопке + бейдж)
- `order_service/tests/test_order_close_validation.py` (новый)

**Реализация:**

Backend — при попытке перевода `* → CLOSED`:
```python
if new_status == OrderStatus.CLOSED:
    if order.payment_type == PaymentType.TRADE_CREDIT:
        if not order.trade_credit_contract_signed:
            raise HTTPException(400, "Cannot close: trade credit contract not signed")
    else:
        if order.payment_status != PaymentStatus.PAID:
            raise HTTPException(400, "Cannot close: order is not fully paid")
```

Frontend:
- В карточке заявки бейдж «Ожидает оплаты» если `status ∈ {DELIVERED, PARTIALLY_DELIVERED} AND payment_status ≠ paid`
- Кнопка «Закрыть заявку» disabled при невыполненных условиях, tooltip объясняет почему

**Критерии приёмки:**
- [ ] Тест: попытка закрыть unpaid заявку через API → 400 с понятным сообщением
- [ ] Тест: закрытие paid заявки → 200
- [ ] Тест: закрытие trade_credit с `contract_signed=true` → 200, без подписи → 400
- [ ] Ручная проверка в UI: бейдж и disabled-кнопка работают

**Коммит:** `feat(orders): block CLOSE transition until payment received`

---

## Шаг 1.4. CRUD реквизитов юрлица

**Цель:** админ может управлять реквизитами юрлица. История сохраняется.

**Файлы:**
- `order_service/app/routers/legal_entities.py` (новый)
- `order_service/app/schemas/legal_entity.py` (новый)
- `order_service/app/services/legal_entity_service.py` (новый)
- `order_service/app/main.py` (подключить роутер)
- `frontend/src/pages/Finance/LegalEntities.tsx` (новый — подвкладка)

**Endpoints (только admin):**
- `GET /api/legal-entities` — список (вся история, сорт по `effective_from desc`)
- `GET /api/legal-entities/current` — текущие реквизиты (один объект)
- `POST /api/legal-entities` — создать новые. Сервис:
  1. У текущей записи проставляет `effective_to=now()`, `is_current=false`
  2. Создаёт новую запись с `effective_from=now()`, `is_current=true`
  Обе операции в одной транзакции.
- `GET /api/legal-entities/{id}` — конкретная запись

**Критерии приёмки:**
- [ ] Тест: при создании новых реквизитов старые автоматически закрываются
- [ ] Тест: в любой момент `current` возвращает ровно одну запись
- [ ] UI: админ видит текущие реквизиты + историю, может создать новые

**Коммит:** `feat(orders): legal entity CRUD with history`

---

## Шаг 1.5. Генерация PDF документов

**Цель:** счета, УПД и ТТН генерируются автоматически на ключевых переходах.

**Файлы:**
- `order_service/requirements.txt` (+ `WeasyPrint`, `Jinja2`)
- `order_service/Dockerfile` (системные зависимости для WeasyPrint: `libpango`, `libcairo` и т.д.)
- `order_service/app/services/document_service.py` (новый)
- `order_service/app/templates/documents/invoice_preliminary.html` (новый)
- `order_service/app/templates/documents/invoice_final.html` (новый)
- `order_service/app/templates/documents/upd.html` (новый)
- `order_service/app/templates/documents/ttn.html` (новый)
- `order_service/app/templates/documents/_base.html` (новый — общая обвязка)
- `order_service/app/routers/documents.py` (новый)
- `order_service/app/schemas/document.py` (новый)
- `docker-compose.yml` (volume для документов)

**Реализация:**

### Хранение
- Локальный volume `documents_data:` смонтирован в `order_service` как `/app/documents/`
- Структура: `/app/documents/{order_id}/{type}_{timestamp}.pdf`
- В таблице `documents.file_path` — относительный путь от корня storage

### `document_service.py`
Функции:
- `generate_invoice_preliminary(db, order)` → создаёт PDF + запись в `documents`
- `generate_invoice_final(db, order)`
- `generate_upd(db, order)`
- `generate_ttn(db, order)`

Каждая:
1. Загружает текущие реквизиты юрлица
2. Рендерит Jinja2-шаблон с данными заявки + реквизитами
3. WeasyPrint → PDF в файл
4. Создаёт запись в `documents` с `legal_entity_snapshot = current_legal_entity.to_dict()`
5. Возвращает Document

### Шаблоны
- Заглушки (минимально валидные документы) на старте — макет уточним по образцу от пользователя
- Использовать таблицы для построчных позиций
- Шрифт DejaVu Sans (поддержка кириллицы)
- В `_base.html` — стиль шапки, подвала, отступы

### Триггеры генерации
- При создании Order с `payment_type=prepaid` → `generate_invoice_preliminary`
- При установке `final_amount` (= переход в DELIVERED / PARTIALLY_DELIVERED) → `generate_invoice_final`, `generate_upd`, `generate_ttn`
- `quality_cert` — отдельный endpoint для ручной загрузки (`POST /api/orders/{id}/documents/quality-cert` с файлом)

### Endpoints
- `GET /api/orders/{id}/documents` — список документов заявки (всем участникам заявки)
- `GET /api/documents/{id}/download` — скачивание PDF (signed URL или token-protected)
- `POST /api/orders/{id}/documents/quality-cert` — загрузка `quality_cert` (только manager/admin)
- `POST /api/orders/{id}/documents/regenerate/{type}` — ручная перегенерация (только admin)

**Критерии приёмки:**
- [ ] Создание prepaid-заявки → автоматически создаётся `invoice_preliminary.pdf`, открывается, читается, реквизиты в нём = текущим реквизитам юрлица
- [ ] Перевод заявки в DELIVERED → создаются 3 файла (invoice_final, upd, ttn)
- [ ] Документы доступны по `GET /api/orders/{id}/documents` участникам
- [ ] При смене реквизитов юрлица новые документы используют новые реквизиты, старые — содержат старый snapshot
- [ ] Загрузка `quality_cert` через UI/API работает

**Коммит:** `feat(orders): PDF document generation (invoice, UPD, TTN) with legal entity snapshot`

> **Открытый вопрос для пользователя:** макеты PDF — заглушки на старте, итеративно правим по образцам, которые пользователь пришлёт позже.

---

## Шаг 1.6. Вкладка «Финансы»

**Цель:** админ/менеджер видит сводку по деньгам, фильтрует, экспортирует.

**Файлы:**
- `order_service/app/routers/finance.py` (новый)
- `order_service/app/services/finance_service.py` (новый)
- `order_service/app/schemas/finance.py` (новый)
- `frontend/src/pages/Finance/index.tsx` (новый)
- `frontend/src/pages/Finance/Overview.tsx` (новый)
- `frontend/src/pages/Finance/LegalEntities.tsx` (из шага 1.4)
- Маршрут в роутере фронта, пункт меню для admin/manager

**Endpoints (admin/manager):**

### `GET /api/finance/overview`
Query-параметры:
- `date_from`, `date_to` (по умолчанию: последние 30 дней)
- `payment_status` (опционально: unpaid/partially_paid/paid/overpaid)
- `payment_type` (опционально)
- `client_id`, `manager_id` (опционально)

Response:
```json
{
  "totals": {
    "orders_count": 42,
    "expected_total": 1500000.00,
    "final_total": 1480000.00,
    "paid_total": 1300000.00,
    "debt_total": 180000.00,
    "overpaid_total": 5000.00
  },
  "orders": [
    {
      "order_id": 123,
      "order_number": "BO-2026-00123",
      "created_at": "2026-05-01T...",
      "client_name": "ООО Ромашка",
      "manager_name": "Иванов И.И.",
      "payment_type": "prepaid",
      "status": "DELIVERED",
      "payment_status": "partially_paid",
      "expected_amount": 50000.00,
      "final_amount": 48000.00,
      "paid_amount": 30000.00,
      "debt": 18000.00
    },
    ...
  ]
}
```

### `GET /api/finance/export?format=csv`
Тот же запрос → CSV (или XLSX через `openpyxl`).

### Frontend
- Таблица заявок с финансовыми колонками
- Фильтры в шапке
- Итоговая строка снизу (агрегаты)
- Кнопка «Экспорт CSV»
- Подвкладка «Реквизиты юрлица»

**Критерии приёмки:**
- [ ] На seed-данных вкладка отображает корректные суммы
- [ ] Все фильтры работают (можно проверить через тест и UI)
- [ ] Экспорт CSV скачивается и открывается в Excel/Numbers без проблем с кодировкой (UTF-8 BOM)
- [ ] Подвкладка «Реквизиты юрлица» интегрирована

**Коммит:** `feat(frontend): finance overview page with filters and export`

---

## Шаг 1.7. Отправка документов в чат

**Цель:** менеджер из чата с клиентом одним кликом отправляет нужный документ.

**Файлы:**
- `chat_service/app/models/message.py` (новый тип сообщения)
- `chat_service/app/alembic/versions/0002_document_attachment_message_type.py`
- `chat_service/app/routers/messages.py` (поддержка нового типа)
- `chat_service/app/services/...` (логика)
- `order_service/app/routers/documents.py` (endpoint для chat: список документов клиента)
- `frontend/src/components/Chat/AttachDocumentDialog.tsx` (новый)
- `frontend/src/components/Chat/MessageRenderer.tsx` (рендер карточки document_attachment)

**Реализация:**

### Сообщения в чате — новый тип
- В `messages.type` добавить `document_attachment` (наряду с `text`, `file`, и т.д.)
- `payload`: `{document_id, document_type, file_name, order_number}`

### Endpoint для UI чата
`GET /api/orders/documents/by-client/{client_id}?order_id={optional}`
- Возвращает список документов клиента (фильтр по конкретной заявке если задан `order_id`)
- Только для manager/admin
- Используется в диалоге «Прикрепить документ»

### Frontend
- В компоненте чата (где скрепка/прикрепить файл) — новая опция «Документ из заявки»
- Открывает диалог: дропдаун заявок клиента → список документов этой заявки → клик «Прикрепить»
- При отправке: создаётся сообщение типа `document_attachment` через WebSocket/API
- При рендере: карточка с иконкой типа документа, именем файла, кнопкой «Скачать»

### Фиксация просмотра
- При первом скачивании клиентом (`GET /api/documents/{id}/download` от пользователя с ролью client) → если `sent_to_client_at` ещё null, проставить = now()
- В UI менеджера: бейдж «Просмотрено клиентом» на карточке документа в чате

**Критерии приёмки:**
- [ ] Менеджер в чате открывает диалог, видит документы по заявкам клиента, отправляет один
- [ ] У клиента в чате появляется карточка, по клику скачивается PDF
- [ ] После скачивания клиентом — у менеджера видна метка «просмотрено» (через рефреш чата)
- [ ] Document_attachment сообщения корректно отображаются в истории чата

**Коммит:** `feat(chat): send order documents as chat attachments`

---

## Шаг 1.8. Регрессионная проверка и накат на прод

**Цель:** Этап 1 целиком работает на dev, миграция на прод без потерь.

**Чеклист регрессионной проверки на dev (с seed-данными):**

Сценарий A — prepaid:
- [ ] Менеджер создаёт заявку для клиента с `payment_type=prepaid`
- [ ] Автоматически генерится `invoice_preliminary`
- [ ] Менеджер отправляет счёт в чат → клиент скачивает
- [ ] Менеджер фиксирует оплату → `payment_status = paid`
- [ ] Водитель доставляет → DELIVERED → генерится `invoice_final`, `upd`, `ttn`
- [ ] Менеджер закрывает заявку → CLOSED

Сценарий B — on_delivery:
- [ ] Создание заявки → IN_PROGRESS → IN_TRANSIT → DELIVERED
- [ ] Документы генерятся при DELIVERED
- [ ] Попытка закрыть `payment_status=unpaid` → 400
- [ ] Фиксация оплаты → CLOSED работает

Сценарий C — trade_credit:
- [ ] Создание заявки → доставка → `final_amount` известен
- [ ] Попытка закрыть без `trade_credit_contract_signed` → 400
- [ ] Установка `contract_signed=true` → закрытие работает, даже если `payment_status=unpaid`

Сценарий D — переплата:
- [ ] Prepaid заявка, клиент платит 100 000
- [ ] Доставлено меньше, `final_amount=80 000`
- [ ] `payment_status=overpaid`, в UI бейдж
- [ ] Админ в «Финансах» видит переплату в итогах

Сценарий E — частичная оплата:
- [ ] Клиент платит 50% → `partially_paid`
- [ ] Доставка → DELIVERED
- [ ] Попытка закрыть → 400
- [ ] Клиент платит остаток → `paid` → закрытие работает

**Накат на прод (после прохождения чеклиста на dev):**
1. **Бэкап** всех 4 БД (`./scripts/backup_db.sh`)
2. `git pull` на проде
3. `docker compose build` (для новых системных зависимостей WeasyPrint)
4. `docker compose up -d` — миграции применятся через entrypoint
5. **Smoke-тест:**
   - Логин под админом
   - Создание тестовой заявки
   - Проверка вкладки «Финансы»
6. Если что-то пошло не так — `docker compose down && pg_restore` из бэкапа, разбор инцидента

**Обновить `CLAUDE.md` в репо:**
- Добавить факты о новых таблицах
- Зафиксировать Alembic-флоу
- Описать запрет ручных ALTER

**Коммит:** `chore: stage 1 release notes and CLAUDE.md updates`

---

# Что НЕ делать в этом плане

- ❌ Email-уведомления о документах (отложено на 1.6 как «опциональный шаг» — не делаем сейчас)
- ❌ Интеграцию с банком/онлайн-оплату — отдельный этап
- ❌ Звонки в чате — Этап 2, после этого SPEC
- ❌ Мобильные приложения — Этап 3, отдельный SPEC
- ❌ Любые UI-улучшения сверх описанного — записать в TODO.md, не делать
- ❌ Рефакторинг существующих модулей «попутно» — каждое изменение должно иметь явное обоснование

---

# Открытые вопросы (требуют ответа пользователя по ходу)

1. **Макеты PDF документов** — на старте делаем минимальные заглушки. Пользователь пришлёт образцы (Word/PDF/печатные) → итеративно подгоним.
2. **Облачное хранилище для бэкапов** — настраивается позже, заглушка готова.
3. **Хранение PDF документов** — стартуем с локального volume. Миграция на S3 — отдельная задача в будущем (когда объёмы потребуют).

---

# ЭТАП 1.5 — Тарифы и расширенные типы оплат

> Расширение Этапа 1, утверждено 2026-05-14. Цель: довести систему оплат и ценообразования до полного MVP до перехода к Этапу 2 (LiveKit).
>
> Ключевые решения, зафиксированные с пользователем:
> 1. **Тарифы:** цена за литр на каждый `fuel_type` + ступенчатые скидки по объёму (volume thresholds → % discount).
> 2. **`trade_credit` vs `debt`:** семантика идентична (обе разрешают закрытие без оплаты, но создают долг). Разделены **только для бухгалтерской отчётности** — никакой разной бизнес-логики, никаких дополнительных полей.
> 3. **MVP-скоуп:** включает авто-генерацию документов (опирается на инфру Шага 1.5 «Генерация PDF документов»). Триггеры расширяются под новые типы оплат.
>
> **До конца Этапа 1.5 — не трогать LiveKit/звонки/мобилку.** TODO.md для всего, что не входит.

---

## Контекст (что уже есть в коде)

- `auth_service`: `ClientProfile.client_type` (enum `INDIVIDUAL` / `COMPANY`), `credit_allowed: bool`. Уже работают, миграция в `0001_baseline.py`.
- `auth_service`: `ClientProfile.fuel_coefficient`, `delivery_coefficient` — **устаревают**, заменяются тарифом. План удаления — Шаг 1.5.3.
- `order_service`: `PaymentType` enum = `prepaid`, `on_delivery`, `trade_credit`, `postpaid`. Хранится в БД lowercase (через `values_callable`). Миграция `0002`.
- JWT в order_service содержит только `sub`+`role`. Получение `client_type`/`credit_allowed`/`tariff_id` — через HTTP к auth_service (паттерн уже используется, см. `_auto_start_trip` в `order_service/app/services/order_service.py`).
- Документы и таблица `documents` уже в `0002`. Авто-генерация прикручена в Шаге 1.5 базового SPEC — расширяем триггеры, не переписываем.

---

## Шаг 1.5.1. Добавление `debt` в `PaymentType`

**Цель:** новый тип оплаты `debt` в enum, без изменения бизнес-логики относительно `trade_credit`.

**Файлы:**
- `order_service/app/models/order.py` (правка enum)
- `order_service/app/services/order_service.py` (правка валидаций, гейтов закрытия)
- `order_service/alembic/versions/0003_payment_type_debt_and_tariffs.py` (новый — общая миграция Этапа 1.5)

**Реализация:**
1. `PaymentType`: добавить значение `DEBT = "debt"`.
2. Гейт закрытия (`* → CLOSED`): обращаться с `DEBT` ровно как с `TRADE_CREDIT` — допускать закрытие при `trade_credit_contract_signed=true`. Назвать переменную/проверку `is_credit_payment = payment_type in (TRADE_CREDIT, DEBT)` для читаемости.
3. Валидация при создании заявки (клиент vs менеджер):
   - Клиент **не может выбирать** `postpaid`, `trade_credit`, `debt` — только `prepaid` или `on_delivery`.
   - Менеджер/админ выбирает любой из доступных по правилам Шага 1.5.6.
4. Миграция: `ALTER TYPE paymenttype ADD VALUE 'debt'`. **Важно:** PG запрещает использовать новое значение в той же транзакции — выполнять в отдельной миграции либо использовать паттерн «type swap через CASE» (как в `0002`). Решение: оставить `ALTER TYPE ADD VALUE` в отдельной transactional блок (`op.execute(...).execution_options(autocommit_block=True)`) — проверить, что Alembic это поддерживает; если нет — type-swap паттерн.

**Критерии приёмки:**
- [ ] Миграция `0003` применяется и откатывается чисто на dev
- [ ] Тест: заявка с `payment_type=debt`, `contract_signed=false` → 400 при закрытии
- [ ] Тест: заявка с `payment_type=debt`, `contract_signed=true` → CLOSED разрешён даже при unpaid
- [ ] Тест: клиент с ролью `client` пытается создать заявку с `payment_type=debt` → 403/400

**Коммит:** `feat(orders): add 'debt' payment type (accounting twin of trade_credit)`

---

## Шаг 1.5.2. Модель тарифов

**Цель:** админ управляет тарифами; каждый тариф = базовая цена за литр на топливо + опциональные ступенчатые скидки.

**Файлы:**
- `order_service/app/models/tariff.py` (новый)
- `order_service/app/models/__init__.py` (экспорт)
- `order_service/alembic/versions/0003_payment_type_debt_and_tariffs.py` (в той же миграции 0003)

**Схема:**

### `tariffs`
```
id              UUID PK
name            varchar(120)  UNIQUE  — например, "Базовый", "Промо-2026", "VIP"
is_default      bool          — ровно одна запись с true; контролируется в сервисе
description     text NULL
is_archived     bool default false
created_by_id   UUID NULL    — admin user
created_at      timestamptz
updated_at      timestamptz
```
**Инвариант:** ровно один тариф с `is_default=true and is_archived=false`. Поддерживается в сервисном слое (транзакция: снять старый default → поставить новый).

### `tariff_fuel_prices`
```
id           UUID PK
tariff_id    UUID FK -> tariffs ON DELETE CASCADE
fuel_type    paymenttype enum (правильно: fueltype) — Diesel*/Petrol*/FuelOil
price_per_liter  Numeric(10, 4)  — рубли за литр
UNIQUE(tariff_id, fuel_type)
```
**Правило:** при создании/редактировании тарифа админ должен задать цену на каждое значение `FuelType`, иначе валидация в сервисе отклоняет. На случай добавления нового FuelType — миграция должна заполнить дефолтные цены во всех существующих тарифах (см. ниже).

### `tariff_volume_tiers`
```
id              UUID PK
tariff_id       UUID FK -> tariffs ON DELETE CASCADE
min_volume      Numeric(10, 2)   — порог в литрах, ВКЛЮЧИТЕЛЬНО
discount_pct    Numeric(5, 2)    — % скидки от базовой цены (0..100)
UNIQUE(tariff_id, min_volume)
```
**Правило применения:** при объёме `V` берётся максимальный `min_volume ≤ V` из этого тарифа. Если ступеней нет — скидки 0%.

**Реализация:**
- Один тариф «Базовый» сидируется в миграции 0003: `is_default=true`, цены на все `FuelType` = текущие плейсхолдеры (50–80 руб/л — уточнить у пользователя в чат-диалоге, **не хардкодить молча**, выпустить как `default_prices.json` рядом со скриптом и ссылаться).
- Без ступеней по умолчанию.

**Критерии приёмки:**
- [ ] Миграция создаёт 3 таблицы + базовый тариф
- [ ] Юнит-тест функции `compute_price(tariff_id, fuel_type, volume) -> Decimal` (создать в Шаге 1.5.5)

**Коммит:** `feat(orders): tariff model with per-fuel pricing and volume discount tiers`

---

## Шаг 1.5.3. Привязка клиента к тарифу

**Цель:** у каждого `ClientProfile` есть `tariff_id` (по умолчанию — `is_default=true` тариф). Меняет только админ.

**Файлы:**
- `auth_service/app/models/client_profile.py` (правка)
- `auth_service/alembic/versions/0002_client_tariff.py` (новый)
- `auth_service/app/schemas/client_profile.py` (правка)
- `auth_service/app/services/user_service.py` (правка — назначение default при создании клиента)

**Изменения:**
- В `client_profiles` добавить колонку `tariff_id UUID NULL` (без FK — лежит в другой БД).
- В миграции: backfill всем существующим клиентам `tariff_id` = id базового тарифа.
- **Поля-коэффициенты `fuel_coefficient`, `delivery_coefficient`** — оставить пока, **не удалять** в этой миграции (для возможного отката). Удаление вынести в отдельную задачу TODO.md после подтверждения, что ценообразование через тариф стабильно работает на проде ≥ 1 недели.
- В `ClientProfileCreate`/`Update` схемах: `tariff_id` доступен только админу. В роутерах user_service: эндпоинт назначения тарифа — только admin (`POST /api/admin/clients/{id}/tariff`).

**Замечание про `tariff_id` в auth-БД:** базовый id берём из переменной окружения `DEFAULT_TARIFF_ID` (заполняется при деплое после создания тарифа в order_service). Альтернативно — поле может быть `NULL`, и в логике расчёта `NULL` трактуется как «использовать default». Выбираем второй вариант: меньше связности при миграциях. **Решение зафиксировано: `tariff_id IS NULL → default tariff`.**

**Критерии приёмки:**
- [ ] Новый клиент создаётся без tariff_id → расчёт идёт по default
- [ ] Админ через API назначает клиенту тариф → следующая заявка использует новый
- [ ] Не-админ не может изменить tariff_id (403)

**Коммит:** `feat(auth): assign tariff to client profile (admin-only)`

---

## Шаг 1.5.4. Inter-service: order_service ↔ auth_service

**Цель:** при создании заявки order_service знает `client_type`, `credit_allowed`, `tariff_id` клиента.

**Файлы:**
- `auth_service/app/routers/users.py` (или новый `internal.py`)
- `order_service/app/services/client_context.py` (новый)

**Реализация:**
1. **Новый эндпоинт в auth_service:** `GET /api/internal/clients/{client_id}/context`
   Response:
   ```json
   {
     "user_id": "...",
     "client_type": "individual" | "company",
     "credit_allowed": true,
     "tariff_id": "uuid-or-null"
   }
   ```
   Доступ: только межсервисный (проверка по специальному заголовку/служебному токену — паттерн уже используется для service tokens; смотреть `_make_service_token` в order_service).
2. **В order_service:** `get_client_context(client_id, token) -> ClientContext` — простой httpx-вызов, таймаут 5 с, кешируем в памяти на 30 с (`functools.lru_cache` не годится для async; использовать `cachetools.TTLCache` + lock или сразу без кеша на MVP — без кеша на старте).
3. Вызывается:
   - При создании заявки (Шаг 1.5.5/1.5.6)
   - При попытке изменения `payment_type` менеджером
4. Если auth_service недоступен — **отказать в создании заявки с 503** (не угадывать дефолты по тихому).

**Критерии приёмки:**
- [ ] Эндпоинт `/api/internal/clients/{id}/context` возвращает корректные данные
- [ ] Эндпоинт недоступен без service-токена (401/403)
- [ ] Создание заявки в order_service делает один HTTP-вызов и использует результат

**Коммит:** `feat(auth,orders): internal client context endpoint for cross-service checks`

---

## Шаг 1.5.5. Расчёт `expected_amount` по тарифу

**Цель:** при создании заявки `expected_amount = price_per_liter(tariff, fuel) × volume × (1 - discount_pct/100)`.

**Файлы:**
- `order_service/app/services/pricing_service.py` (новый)
- `order_service/app/services/order_service.py` (интеграция при создании)
- `order_service/tests/test_pricing.py` (новый)

**Логика:**
```
def compute_expected_amount(tariff_id, fuel_type, volume) -> Decimal:
    tariff = fetch tariff (или default если tariff_id is None)
    if tariff is None or archived → raise 500 "Тариф не настроен"
    price = tariff.fuel_prices[fuel_type].price_per_liter
    tiers = tariff.volume_tiers sorted by min_volume desc
    discount_pct = 0
    for t in tiers:
        if volume >= t.min_volume:
            discount_pct = t.discount_pct
            break
    return (price * volume * (1 - discount_pct/100)).quantize(Decimal("0.01"))
```

При создании Order:
- После определения `client_id`, вызвать `get_client_context` → получить tariff_id
- Вызвать `compute_expected_amount(tariff_id, data.fuel_type, data.volume_requested)`
- Записать в `order.expected_amount`

При установке `final_amount` (delivered): пересчёт по тому же тарифу с фактическим объёмом — это `final_amount`. Уже частично описано в Шаге 1.2 базового SPEC; здесь только заменяем источник цены (был "цена в момент создания" — становится «тариф клиента»).

**Замечание по immutability:** если админ поменяет тариф клиента после создания заявки, **expected_amount уже зафиксирован** на момент создания. `final_amount` пересчитывается по тарифу клиента **в момент доставки** — это компромисс «простоты»: на проде с одним менеджером цены меняются редко. Если станет проблемой — записывать `tariff_snapshot_id` в заявку (TODO.md).

**Критерии приёмки:**
- [ ] Юнит-тесты: 0 ступеней, 1 ступень, несколько ступеней, объём ниже всех порогов, объём = порогу (включительно)
- [ ] При создании заявки `expected_amount` появляется автоматически
- [ ] Если у клиента `tariff_id=null` → используется default

**Коммит:** `feat(orders): auto-compute expected_amount from client tariff`

---

## Шаг 1.5.6. Валидация `payment_type` по ролям и типу клиента

**Цель:** только разрешённые комбинации `(actor_role, client_type, credit_allowed) → payment_type` принимаются.

**Файлы:**
- `order_service/app/services/order_service.py` (правка валидации)
- `order_service/tests/test_payment_type_rules.py` (новый)

**Матрица:**
| payment_type | INDIVIDUAL | COMPANY | требует credit_allowed | кто может выбрать |
|---|---|---|---|---|
| `prepaid` | ✅ | ✅ | — | client, manager, admin |
| `on_delivery` | ✅ | ❌ | — | client, manager, admin |
| `postpaid` | ❌ | ✅ | — | manager, admin |
| `trade_credit` | ❌ | ✅ | — | manager, admin |
| `debt` | ✅ | ✅ | **да** | manager, admin |

Реализация: один сервисный метод `validate_payment_type(payment_type, actor_role, client_ctx)`. Бросает `ValidationError` с человеко-понятным русским сообщением.

**Критерии приёмки:**
- [ ] Юнит-тест на все 5×3 = 15 комбинаций минимум
- [ ] Сообщения об ошибке указывают, почему запрещено (роль / тип клиента / credit_allowed)

**Коммит:** `feat(orders): role+client-type validation for payment_type`

---

## Шаг 1.5.7. Admin API: тарифы и назначения

**Цель:** админ CRUD-ит тарифы и назначает их клиентам через REST.

**Файлы:**
- `order_service/app/routers/tariffs.py` (новый)
- `order_service/app/schemas/tariff.py` (новый)
- `order_service/app/services/tariff_service.py` (новый)
- `order_service/app/main.py` (подключить роутер)
- `auth_service/app/routers/admin.py` (или дополнить users — эндпоинт назначения тарифа клиенту)

**Разграничение прав (зафиксировано 2026-05-14):**
- **Базовый (default) тариф** — цены и ступени могут менять **manager И admin** (цены закупки и рыночные ставки прыгают каждый день; менеджер в курсе быстрее, чем админ).
- **Специальные (не-default) тарифы** — CRUD/архивация/`set-default`/назначение клиентам — **только admin**.
- Признак «специального»: `is_default = false`. Эндпоинты применяют это правило на уровне сервиса, не роутера — единая функция `_check_tariff_edit_permission(tariff, actor)`.

**Endpoints:**

### order_service
- `GET /api/tariffs` — список (с архивными по флагу `?include_archived=true`). **Доступ:** manager, admin.
- `GET /api/tariffs/default` — default тариф (для UI клиента). **Доступ:** любой авторизованный.
- `GET /api/tariffs/{id}` — детали с fuel_prices и volume_tiers. **Доступ:** manager, admin.
- `POST /api/tariffs` — создать новый (всегда специальный, `is_default=false`). **Доступ:** только admin.
- `PUT /api/tariffs/{id}` — обновить (заменяет fuel_prices и volume_tiers целиком). **Доступ:** admin для любого; manager только если `tariff.is_default=true`.
- `POST /api/tariffs/{id}/set-default` — пометить default (снять с предыдущего в транзакции). **Доступ:** только admin.
- `POST /api/tariffs/{id}/archive` — архивировать; нельзя архивировать default, нельзя архивировать тариф с активными (не-CLOSED, не-REJECTED) заявками → 400 со списком id. **Доступ:** только admin.

### auth_service
- `POST /api/admin/clients/{client_id}/tariff` — body: `{tariff_id: UUID | null}`. null → сбрасывает в default.
- `PATCH /api/admin/clients/{client_id}/credit-allowed` — body: `{credit_allowed: bool}`.

**Критерии приёмки:**
- [ ] Тесты на все 7 эндпоинтов с happy/sad-path
- [ ] Не-админ получает 403 на любой
- [ ] Архивация тарифа с активной заявкой возвращает понятный список номеров заявок

**Коммит:** `feat(orders,auth): admin tariff CRUD and client assignment endpoints`

---

## Шаг 1.5.8. Frontend: тарифы, фильтрация оплат, credit-флаг

**Цель:** UI отражает новые возможности.

**Файлы:**
- `frontend/index.html` (текущий монолит, см. секции «Финансы», создание заявки, профиль клиента)
- Идеально — выделить шаблоны для тарифов в отдельный модуль, но **не рефакторить index.html попутно**. Минимально-инвазивные правки.

**Изменения:**

### Создание/редактирование заявки
- При выборе клиента — подгрузить `client_context` (тот же `/api/internal/clients/{id}/context`, но через прокси-эндпоинт в order_service для UI, чтобы не светить сервисный токен наружу). Реализовать `GET /api/clients/{id}/payment-options` в order_service — возвращает уже отфильтрованный список доступных `payment_type` под текущего actor'а.
- Radio-кнопки `payment_type` рендерятся динамически по этому списку, с подписями:
  - `prepaid` → «Предоплата»
  - `on_delivery` → «По факту»
  - `postpaid` → «По счёту»
  - `trade_credit` → «Товарный кредит»
  - `debt` → «В долг»
- Если `actor=client` — не показывать `postpaid/trade_credit/debt` вообще.

### Экран профиля клиента (админ)
- Селектор «Тариф» — список из `GET /api/tariffs`
- Чекбокс «Разрешить оплату в долг» (`credit_allowed`)
- Поля коэффициентов — **скрыть** (но не удалять из API на этом этапе; см. 1.5.3)

### Новая страница «Тарифы» (manager + admin, с разными правами)
- Таблица тарифов: name, default-флаг, кол-во клиентов на тарифе (агрегат), архив-статус
- Карточка тарифа: цены по каждому fuel_type + список ступеней скидок
- Формы редактирования с inline-добавлением ступеней
- **Manager:**
  - Видит все тарифы (для контекста)
  - Может **редактировать** только тариф с `is_default=true` (цены и ступени). Кнопки «Создать», «Сделать дефолтом», «Архивировать», «Назначить клиенту» — скрыты или disabled с tooltip «Доступно только администратору»
  - Не видит формы создания нового тарифа
- **Admin:**
  - Полный доступ: создание, редактирование любого, set-default, архивация, назначение
- Отдельный визуальный маркер: блок «Базовый тариф — актуальные цены закупки» наверху страницы, всегда раскрыт. Менеджер видит inline-форму редактирования цен прямо в этом блоке (быстрый кейс «поменять цену дизеля утром»).

**Критерии приёмки:**
- [ ] Клиент-физлицо в форме заказа видит только `prepaid` и `on_delivery` (+ `debt` если флаг)
- [ ] Менеджер для клиента-юрлица видит `prepaid`, `postpaid`, `trade_credit` (+ `debt` если флаг). НЕ видит `on_delivery`.
- [ ] Админ создаёт новый тариф, назначает его клиенту, новая заявка этого клиента имеет `expected_amount` по новому тарифу
- [ ] Архивный тариф не появляется в селекторе при создании клиента

**Коммит:** `feat(frontend): tariff management UI and dynamic payment type filtering`

---

## Шаг 1.5.9. Расширение триггеров авто-документов

**Цель:** документы выпускаются под все 5 типов оплат, не только prepaid и on_delivery (как в базовом SPEC 1.5).

**Файлы:**
- `order_service/app/services/document_service.py` (правка триггеров)
- `order_service/app/services/order_service.py` (хуки на переходах)

**Матрица триггеров:**

| payment_type | при создании заявки | при IN_TRANSIT | при DELIVERED | при CLOSED |
|---|---|---|---|---|
| `prepaid` | invoice_preliminary | — | invoice_final, upd, ttn | — |
| `on_delivery` | — | — | invoice_final, upd, ttn | — |
| `postpaid` | — | — | invoice_final, upd, ttn | — |
| `trade_credit` | — | ttn (предварительно) | invoice_final, upd, ttn (финал) | — |
| `debt` | — | ttn (предварительно) | invoice_final, upd, ttn (финал) | — |

**Замечание:** для `trade_credit`/`debt` ТТН нужна **в момент выезда** (водитель везёт груз с документом), а финальная — после фактической приёмки. Хранятся как две версии (`type=ttn`, разные `generated_at`).

**Quality_cert** — остаётся ручной загрузкой по всем типам оплат (см. базовый Шаг 1.5).

**Критерии приёмки:**
- [ ] Тест-сценарий для каждого `payment_type` создаёт правильный набор документов в правильные моменты
- [ ] При наличии двух ТТН (`trade_credit`) обе доступны в `GET /api/orders/{id}/documents`, отличаются по `generated_at`

**Коммит:** `feat(orders): document triggers extended for all payment types`

---

## Шаг 1.5.10. Регрессия и накат

**Чеклист на dev (с свежим seed):**

Сценарий A — INDIVIDUAL клиент:
- [ ] Видит только `prepaid` / `on_delivery` в UI
- [ ] Создаёт `prepaid` → авто-invoice_preliminary с правильной суммой по default-тарифу
- [ ] Админ задаёт `credit_allowed=true` → клиенту становится виден `debt`
- [ ] Заявка `debt` → закрытие требует contract_signed

Сценарий B — COMPANY клиент:
- [ ] Менеджер видит `prepaid` / `postpaid` / `trade_credit` (без `on_delivery`)
- [ ] Заявка `trade_credit`, IN_TRANSIT → ТТН выпускается; DELIVERED → invoice_final+upd+финальная ТТН
- [ ] Закрытие без contract_signed → 400

Сценарий C — кастомный тариф:
- [ ] Админ создаёт «Промо» тариф со ступенью 5000 л → −10%
- [ ] Назначает клиенту
- [ ] Клиент создаёт заявку 6000 л → expected_amount = price × 6000 × 0.9

Сценарий D — архивация:
- [ ] Архивация default-тарифа → 400
- [ ] Архивация тарифа с активной заявкой → 400 + список номеров

Сценарий E — credit_allowed toggle:
- [ ] Админ снимает флаг → клиент не может создать новую `debt`-заявку
- [ ] Существующие `debt`-заявки клиента работают как раньше (флаг проверяется только на создании)

**Накат на прод:**
1. Бэкап всех 4 БД
2. `git pull && docker compose build && docker compose up -d`
3. Миграции применятся (auth: `0002_client_tariff`, orders: `0003_payment_type_debt_and_tariffs`)
4. Smoke: логин admin → создать новый тариф → назначить тестовому клиенту → создать тестовую заявку
5. Обновить `CLAUDE.md` (Decisions + Gotchas про тарифы)

**Коммит:** `chore: stage 1.5 release notes and CLAUDE.md updates`

---

# Решения Этапа 1.5 (зафиксировано 2026-05-14)

1. **Базовые цены для тарифа «Базовый»** меняются ежедневно (зависят от закупки и рынка) — править через UI вкладки «Тарифы». Менеджер и админ имеют право редактировать default-тариф. Создание/архивация/назначение специальных тарифов — только админ. Миграция 0003 сидирует default placeholder-значениями (например, последние известные рыночные цены, явно помечены в release notes как «обязательно проверить менеджеру в день деплоя»).
2. **Округление денежных значений** (`expected_amount`, `final_amount`, скидки) — до копеек: `Decimal.quantize(Decimal("0.01"), ROUND_HALF_UP)`.

# Открытые вопросы Этапа 1.5

1. **«Доставка» в тарифе.** В текущем `ClientProfile` есть `delivery_coefficient` — новый тариф его НЕ покрывает. Решение MVP: доставка включена в `price_per_liter`. Отдельная строка тарифа на доставку — TODO.md.

---

# История изменений SPEC

- 2026-05-13 — Initial: Этап 0 + Этап 1
- 2026-05-14 — Этап 1.5: тарифы, `debt`, фильтрация payment_type, расширение авто-документов
