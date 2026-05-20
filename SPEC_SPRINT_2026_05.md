# SPEC — Спринт 2026-05 (заказ-релиз после встречи)

**Контекст.** После встречи с заказчиком 2026-05-19. Меняем 10 точек по UX/моделям, готовим почву для следующего спринта (автогенерация документов).

**Принципы.**
- Работаем только в `master`.
- Спека разбита на **3 деплоя** — каждый деплой независим, тестируется и катится отдельно.
- Все миграции БД — через Alembic, по 1 миграции на деплой.
- Untracked файлы на сервере (`/opt/baltoil/.env`, `/opt/baltoil/tls/`) не трогаем.

---

## Деплой 1 — UX/модельные правки (приоритет высокий)

Объём: ~10 часов Sonnet. Не требует внешних интеграций.

### 1.1 Интервалы доставки вместо точного времени (#1)

**Что.** Заменить выбор точного времени на 4 фиксированных интервала: `07:00-13:00`, `13:00-16:00`, `16:00-20:00`, `20:00-00:00`.

**Файлы:**
- `order_service/app/models/order.py` — добавить `delivery_window: str` (nullable, длина 11), оставить `desired_date` (используется как дата без времени).
  - Добавить класс `class DeliveryWindow(str, enum.Enum): MORNING="07-13"; AFTERNOON="13-16"; EVENING="16-20"; NIGHT="20-24"`.
- `order_service/app/schemas/order.py` — поле `delivery_window: DeliveryWindow` в create/update/response.
- `order_service/alembic/versions/<new>_delivery_window.py` — миграция: `ADD COLUMN delivery_window VARCHAR(11) NULL`. Для старых заявок оставляем NULL (UI покажет "не указан").
- `frontend/index.html` — в форме создания заявки заменить time picker на `<select>` с 4 значениями. В карточке заявки и в списках — показывать "Доставка: 13–16".

**Acceptance:**
- Создать заявку → выбор интервала, без поля времени
- В карточке заявки видно "Дата: 20.05.2026, окно: 13–16"
- Старые заявки без `delivery_window` — отображаются без ошибки

### 1.2 Убрать приоритет (#3)

**Что.** Убрать поле "приоритет (обычная/срочная)" из UI создания заявки. Поле `priority` в БД оставить (используется в фильтрах админа в будущем), но всегда = `normal` при создании.

**Файлы:**
- `frontend/index.html` — убрать селектор priority из формы создания.
- `order_service/app/schemas/order.py` — `OrderCreateRequest.priority` сделать опциональным с дефолтом `NORMAL`.
- `order_service/app/services/order_service.py` — `priority` всегда `NORMAL` для не-staff (уже так), для staff тоже принудительно `NORMAL` пока в форме нет селектора.

**Acceptance:**
- В форме создания заявки нет поля priority
- В БД все новые заявки = `normal`

### 1.3 Новый статус-флоу: заявки сразу доступны водителям (#4, вариант A2)

**Что.** Заявка `NEW` сразу доступна всем активным водителям. Любой водитель может взять её → переход в `ASSIGNED` (или `IN_PROGRESS`, выбрать одно — см. ниже). Менеджер может вмешаться (отменить, переназначить) — без отдельного "подтверждения".

**Решение:** оставляем `IN_PROGRESS` как алиас "взято в работу" — это **общий** статус для случая "водитель взял". `ASSIGNED` (legacy) убираем из активного использования, миграцией перевести существующие `ASSIGNED` → `IN_PROGRESS`.

**Файлы:**
- `order_service/app/models/order.py` — в комментарии к `OrderStatus.ASSIGNED` пометить как deprecated.
- `order_service/app/services/order_service.py`:
  - В `take_order(order_id, driver_id)`: разрешить переход `NEW → IN_PROGRESS` если `current_status == NEW` (раньше требовался манагер). Установить `driver_id`. Логировать в `OrderStatusLog`.
  - В `transition_status`: убрать обязательность `manager_id` для перехода `NEW → IN_PROGRESS`.
- `order_service/app/routers/orders.py`:
  - Эндпоинт `POST /api/v1/orders/{id}/take` (если нет — создать) — доступен `role=driver`. Без проверки наличия `manager_id`.
  - `GET /api/v1/orders` для роли `driver`: возвращать `status in (NEW, IN_PROGRESS where driver_id=self, ...)`. Сейчас, возможно, фильтр `NEW` отсутствует — проверить.
- `order_service/alembic/versions/<new>_status_remap.py` — `UPDATE orders SET status='in_progress' WHERE status='assigned'`.
- `frontend/index.html`:
  - В роли driver: вкладка "Доступные заявки" показывает `status=NEW` (всем водителям, не привязанные). Кнопка "Взять заявку" → POST /take.
  - В роли manager: видит `NEW` сразу, без кнопки "Подтвердить". Только "Отменить" / "Переназначить" / комментарий.
  - Убрать любые UI-элементы про "подтвердить".

**Acceptance:**
- Водитель видит `NEW` заявки и может взять без участия менеджера
- Менеджер видит `NEW` заявки одновременно
- Менеджер может отменить или переназначить заявку в любом статусе ≤ DELIVERED

### 1.4 Email + телефон в списках клиентов (#10b)

**Что.** В таблицах клиентов (для менеджера/админа) добавить колонки `email`, `phone`. Поиск по email/phone уже есть в эндпоинте `/users` — проверить.

**Файлы:**
- `frontend/index.html` — в рендере списка клиентов (страница "Клиенты"): добавить колонки.
- `auth_service/app/routers/users.py` — убедиться что `UserDirectoryEntry` возвращает `email` и `phone`. Если нет — добавить.

**Acceptance:**
- Таблица "Клиенты" показывает email и phone
- Поиск работает по email и phone

### 1.5 Пересчёт суммы по факту (#9)

**Что.** При закрытии заявки `expected_amount = volume_delivered * price_per_liter`. Сейчас сумма фиксируется на создании по `volume_requested`. Если водитель привёз меньше — сумма не уменьшилась.

**Файлы:**
- `order_service/app/services/order_service.py`:
  - В обработчике перехода `IN_TRANSIT → DELIVERED` или `PARTIALLY_DELIVERED`:
    ```python
    actual_volume = order.volume_delivered or order.volume_requested
    price = await get_price(order.fuel_type, order.client_id)  # тариф клиента
    order.final_amount = (Decimal(actual_volume) * price).quantize(Decimal("0.01"))
    ```
  - `expected_amount` не трогаем (это была "ожидаемая на создании"). `final_amount` — реальная.
  - Если `volume_delivered > volume_requested` — разрешаем, сумма растёт. Логируем в `OrderStatusLog`.
- `frontend/index.html` — в карточке заявки после доставки показывать ОБЕ суммы: "Ожидалось: X ₽, факт: Y ₽".

**Acceptance:**
- Если фактический объём меньше — `final_amount` пересчитан вниз
- Если больше — пересчитан вверх
- Старые закрытые заявки не пересчитываются (миграции не нужно)

### 1.6 Постоплата для физлиц всегда (#2)

**Что.** При создании заявки физлицом — НЕТ выбора способа оплаты. По умолчанию `postpaid` (или `on_delivery`, см. ниже). При закрытии:
- Водитель отмечает "оплачено" → `payment_status=paid`, `payment_type=on_delivery`
- Не оплачено + есть `credit_limit ≥ final_amount` → `payment_status=unpaid`, `payment_type=debt`
- Не оплачено + лимита нет → блок закрытия с сообщением "Требуется одобрение менеджера или оплата"; менеджер вручную меняет на `debt` через override-эндпоинт

**Решение по дефолту:** ставим `payment_type=on_delivery` при создании (это "по факту при прибытии"). Если в итоге не оплачено и есть лимит — водитель/менеджер меняет на `debt` при закрытии.

**Файлы:**
- `auth_service/app/models/client_profile.py` — добавить `credit_limit: Decimal | None` (nullable, default NULL). NULL = лимита нет.
- `auth_service/alembic/versions/<new>_credit_limit.py` — миграция.
- `auth_service/app/routers/internal.py` — `ClientContextResponse` отдаёт `credit_limit`.
- `order_service/app/schemas/order.py`:
  - `OrderCreateRequest.payment_type` сделать опциональным, для физлиц — игнорируется (всегда `on_delivery`).
  - Для юрлиц — оставить выбор (prepaid / postpaid / trade_credit).
- `order_service/app/services/order_service.py`:
  - При создании: если `client_type=individual` → `payment_type = on_delivery`.
  - В обработчике закрытия (`CLOSED`): новая логика проверки `credit_limit`.
- `order_service/app/routers/orders.py`:
  - `POST /orders/{id}/close` принимает `{paid: bool, paid_amount?: Decimal}`. Если `paid=False`:
    - Если `client.credit_limit and credit_limit >= final_amount` → допустимо, ставим `payment_type=debt`.
    - Иначе 409 Conflict с сообщением; менеджер использует `POST /orders/{id}/close/override` (роль `manager|admin`).
- `frontend/index.html`:
  - В форме создания заявки для роли client + client_type=individual — поле "Способ оплаты" скрыто.
  - В диалоге закрытия заявки для водителя — чекбокс "Клиент оплатил". Если не отмечен и нет credit_limit → показать "Нужно одобрение менеджера".

**Acceptance:**
- Физлицо создаёт заявку → нет выбора оплаты
- Закрытие без оплаты с credit_limit → `payment_type=debt`, `payment_status=unpaid`
- Закрытие без оплаты без credit_limit → блок, требует менеджера

### Деплой 1: тесты и выкатка

**Smoke-тесты после деплоя:**
1. Создать заявку физлицом — нет полей time/priority/payment, есть `delivery_window`
2. Создать заявку юрлицом — те же поля + есть выбор payment_type
3. Войти водителем — видны `NEW` заявки в "Доступных", кнопка "Взять"
4. Взять заявку — статус `IN_PROGRESS`, `driver_id=self`
5. Закрыть с `volume_delivered < volume_requested` — `final_amount` пересчитан
6. Закрыть без оплаты у клиента с `credit_limit=10000` и `final_amount=5000` → `payment_type=debt`
7. В списке клиентов видны email + phone

**Deploy:** `git push origin master` → на сервере `git pull && docker compose up -d --build` → проверить миграции прошли, контейнеры `Up`.

---

## Деплой 2 — ИНН + короткий номер клиента

Объём: ~5 часов Sonnet. Требует токен DaData.

### 2.1 Интеграция DaData по ИНН (#5)

**Предварительное действие пользователя.** Завести аккаунт на dadata.ru, получить API-токен (бесплатный тариф 10k запросов/день). Положить в `auth_service/.env` как `DADATA_API_KEY=...`.

**Файлы:**
- `auth_service/app/services/dadata_service.py` — новый. Простая обёртка:
  ```python
  async def lookup_by_inn(inn: str) -> dict | None:
      """Returns {company_name, kpp, ogrn, legal_address, director_name} or None."""
  ```
  Использует `httpx.AsyncClient`, эндпоинт `https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party`.
  Таймаут 5с. При ошибке/таймауте — возвращает None (UI просит ввести руками).
- `auth_service/app/config.py` — `dadata_api_key: str | None = None`.
- `auth_service/app/routers/auth.py`:
  - Новый эндпоинт `GET /api/v1/auth/lookup/inn?inn=...` — без авторизации (но rate-limit как у register). Возвращает `{found: bool, data: {company_name, kpp, ogrn, legal_address}}`.
- `frontend/nginx.conf` — добавить exact-match location для `/api/auth/api/v1/auth/lookup/inn` под зону `register_zone` (с тем же `rewrite` фиксом).
- `frontend/index.html` — форма регистрации юрлица:
  - Шаг 1: только поле ИНН + кнопка "Найти".
  - Шаг 2 (после нажатия): автозаполнены `company_name`, `kpp`, `ogrn`, `legal_address`. Поле "Электронная почта", "Телефон", "Пароль". Можно поправить любое автозаполненное.
  - Если ИНН не найден → переход к ручному вводу.

**Acceptance:**
- Регистрация юрлица: ввести ИНН → данные подтянулись → ввести email/pwd → регистрация прошла
- ИНН не найден → ввод руками работает как раньше

### 2.2 Короткий номер клиента (#10a, F1)

**Что.** Каждый клиент получает уникальный целочисленный номер. Отображается как `C-00042` (формат `C-{int:05d}`).

**Файлы:**
- `auth_service/app/models/client_profile.py` — `client_number: Mapped[int] = mapped_column(Integer, unique=True, index=True, autoincrement=True)`. Или PostgreSQL SEQUENCE отдельно — но проще `autoincrement` + `nextval`.
  - Подход: завести SEQUENCE `client_number_seq`, default `nextval('client_number_seq')`. Стартовое значение 1.
- `auth_service/alembic/versions/<new>_client_number.py` — миграция:
  ```sql
  CREATE SEQUENCE client_number_seq START 1;
  ALTER TABLE client_profiles ADD COLUMN client_number INTEGER UNIQUE NOT NULL DEFAULT nextval('client_number_seq');
  ```
  Существующие клиенты получат номера автоматически в порядке создания (через ORDER BY created_at — но defaults на UPDATE не работают, потребуется явный backfill, см. ниже).
  Backfill отдельным шагом:
  ```sql
  WITH ordered AS (SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) AS rn FROM client_profiles)
  UPDATE client_profiles SET client_number = ordered.rn FROM ordered WHERE client_profiles.id = ordered.id;
  SELECT setval('client_number_seq', (SELECT MAX(client_number) FROM client_profiles));
  ```
- `auth_service/app/schemas/user.py`, `client_profile.py` — добавить `client_number: int` в ответы.
- `auth_service/app/routers/users.py` — фильтр `?client_number=42` для поиска.
- `frontend/index.html`:
  - Везде где сейчас UUID клиента — показывать `C-{:05d}`.
  - В деталях клиента — оба: и UUID (мелким, для отладки), и короткий номер крупно.
  - Поиск клиентов: добавить поле "По номеру C-...".

**Acceptance:**
- Все существующие клиенты получили номера 1..N (по дате создания)
- Новый клиент получает следующий номер
- Менеджер ищет клиента по `42` → находит `C-00042`

### Деплой 2: тесты

1. POST `/api/v1/auth/lookup/inn?inn=7707083893` → возвращает "ПАО Сбербанк" (тестовый ИНН)
2. Регистрация юрлица через UI с автозаполнением
3. Все существующие клиенты в списке имеют номер
4. Поиск по `42` находит клиента C-00042

---

## Деплой 3 — Перестройка диалогов (большой)

Объём: ~12 часов Sonnet. Самая сложная часть. Сюда же — снос старых диалогов.

### 3.0 Снос старых диалогов (#6 prereq)

**Файлы:**
- `chat_service/alembic/versions/<new>_drop_conversations.py`:
  ```sql
  TRUNCATE TABLE messages, conversations, conversation_participants CASCADE;
  ```
- Перед миграцией предупредить: всё содержимое чатов сносится.

### 3.1 Новая структура `Conversation` (#6, #7, #8)

**Что.** Три типа диалогов:
- `client_manager` — один на клиента. Участники: клиент + любой активный менеджер/админ. Динамический пул.
- `client_driver_order` — на каждую активную заявку. Участники: клиент + назначенный водитель. Авто-создаётся при `take_order`. Архивируется при `CLOSED`.
- `staff_group` — три преднастроенных: `general`, `drivers`, `managers`. Динамические участники по ролям.

**Файлы:**
- `chat_service/app/models/conversation.py`:
  - Добавить `kind: Mapped[str]` (enum `client_manager`, `client_driver_order`, `staff_group`).
  - `client_id: UUID | None`, `order_id: UUID | None`, `group_code: str | None` (general/drivers/managers).
  - Уникальные индексы:
    - `kind='client_manager'`: уникален по `client_id`
    - `kind='client_driver_order'`: уникален по `order_id`
    - `kind='staff_group'`: уникален по `group_code`
  - `is_archived: bool` (для архивации `client_driver_order` после CLOSED).
- `chat_service/alembic/versions/<new>_conv_kinds.py` — добавить колонки + индексы.

### 3.2 Динамическое членство в `staff_group` и `client_manager`

**Подход.** Не храним список participants для `staff_group` и `client_manager` в БД. Membership вычисляется на лету в каждом запросе.

- `client_manager`: клиент = `client_id`, плюс все `users where role in (manager, admin) and is_active=true`.
- `staff_group general`: все `users where is_active=true and role != client`.
- `staff_group drivers`: все `users where role=driver and is_active=true`.
- `staff_group managers`: все `users where role in (manager, admin) and is_active=true`.

**Файлы:**
- `chat_service/app/services/membership.py` — новый. Один метод `is_member(user_id, conversation_id) -> bool` через RPC к auth_service (используя `internal_api_secret`).
- `chat_service/app/services/conversation_service.py`:
  - `list_conversations(user)` — собирает 3 типа:
    1. `client_manager` где он клиент, ИЛИ если он менеджер/админ — все `client_manager`.
    2. `client_driver_order` где он клиент или водитель (по `client_id`/`driver_id` через RPC к order_service).
    3. `staff_group` по роли.
  - При отправке сообщения — проверка `is_member` перед записью.

**Реализация без RPC (проще).** Чтобы не плодить inter-service вызовы:
- `chat_service` забирает `role` + `is_active` из JWT (там уже есть `role`). Для `client_driver_order` — хранит `order_client_id` и `order_driver_id` прямо в conversation (snapshot, обновляется при `take_order` через internal callback).

→ **Решение:** делаем snapshot в conversation: `client_id`, `driver_id` хранятся напрямую. Membership = `user.id in (client_id, driver_id)` или (для group/manager) по роли из JWT.

### 3.3 Создание/архивация `client_driver_order` (#7)

**Файлы:**
- `order_service/app/services/order_service.py` — в `take_order`:
  - После `commit` — RPC `POST /api/v1/internal/conversations/ensure_client_driver` на chat_service с `{order_id, client_id, driver_id}`.
- `chat_service/app/routers/internal.py` — новый `POST /internal/conversations/ensure_client_driver`:
  - Создаёт `client_driver_order` если ещё нет.
  - Постит системное сообщение "Водитель {name} принял заявку. Можете связаться напрямую."
- При переходе `CLOSED` — `POST /internal/conversations/archive_driver/{order_id}` (опционально).

### 3.4 Преднастроенные `staff_group` (#8)

**Файлы:**
- `chat_service/app/main.py` — в lifespan при старте: убедиться что 3 записи `staff_group` существуют (general, drivers, managers). Если нет — создать. Системные сообщения "Чат создан".

### 3.5 Frontend (#6, #7, #8)

**Файлы:**
- `frontend/index.html` — секция "Чаты":
  - Для роли `client`:
    - Сверху: "Менеджер" (single conversation, не закрывается).
    - Если есть активные заявки с водителем: "Водитель — заявка ORD-2026-000123".
  - Для роли `driver`:
    - Сверху: "Чат водителей" (staff_group).
    - "Общий чат".
    - Активные заявки: "Клиент — ORD-..." (только пока заявка активна).
  - Для роли `manager`/`admin`:
    - "Чат менеджеров", "Общий чат".
    - Список всех `client_manager` диалогов (от всех клиентов).
- UI кнопки "Создать чат" / выбора темы — убрать (диалоги предопределены).

### Деплой 3: тесты

1. Снос старых диалогов — таблицы пустые
2. Логин клиентом → видит "Менеджер" сразу
3. Клиент пишет менеджеру → менеджер видит
4. Создать заявку → клиент НЕ видит чата с водителем
5. Водитель берёт заявку → у клиента и водителя появляется "Водитель — ORD-..."
6. Закрыть заявку → чат архивируется (либо помечен archived, либо скрыт в UI)
7. Логин водителем → видит "Чат водителей", "Общий"
8. Логин менеджером → видит "Чат менеджеров", "Общий", все client_manager

---

## Что НЕ делаем в этом спринте

- Автогенерация документов (PDF). Заложено на следующий спринт. Изменения этого спринта (#5 ИНН, #10a номер клиента, #9 пересчёт по факту) — фундамент для документов.
- Изменения мобильного приложения. Mobile — Etap 3 по roadmap.
- Полная замена UUID на client_number в API. Внутри API остаются UUID, короткий номер — только для отображения.

## Порядок выполнения

1. Sonnet берёт **Деплой 1**, делает все 6 пунктов, тестирует, деплоит, пушит в master.
2. Жду подтверждения от заказчика что Деплой 1 работает на проде.
3. Sonnet берёт **Деплой 2**. (Перед стартом — токен DaData в `.env` на сервере.)
4. Подтверждение → **Деплой 3**.

Между деплоями — пауза на проверку, чтобы не накапливать риски.
