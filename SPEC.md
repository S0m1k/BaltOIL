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

# История изменений SPEC

- 2026-05-13 — Initial: Этап 0 + Этап 1
