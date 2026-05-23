# SPEC — Спринт 2026-06 (реквизиты, карточка клиента, email, экспорт)

**Контекст.** Заказчик 2026-05-23 попросил пять блоков: расширить регистрацию юрлица с автозаполнением из ФНС, поднять SMTP для дублирования уведомлений в email, расширить страницу клиентов карточкой с документами/платежами/аудитом, добавить xlsx-экспорт по выбранным клиентам, и дать менеджеру выбор канала отправки документов (чат vs email).

**Решения, зафиксированные при планировании.**
- ФНС-данные тянем через **DaData** — у нас уже подключена `/findById/party`, добавляем `/findById/bank` для лукапа по БИК. Альтернативы (Контур.Фокус, API-ФНС) дороже и пока не нужны.
- На регистрации юрлица собираем **только 3 поля** руками: ИНН, БИК, расчётный счёт. Остальное (банк, корр.счёт, наименование, юр.адрес, КПП, ОГРН, ОКВЭД, директор) — автоматом из DaData.
- Корр.счёт **тянем** из DaData по БИК (он есть в ответе), не запрашиваем у клиента.
- `billing_email` — отдельное поле в `ClientProfile`, спрашиваем при регистрации опционально. Если не задан — берём `User.email`.
- SMTP-провайдер: конфиг через ENV (host/port/user/password/from). Рекомендация для прода — **Yandex.360 Бизнес** (~250₽/мес, SPF/DKIM из коробки). На dev можно `mailhog`.
- Email-триггеры: заявка создана / водитель взял / в пути / доставлена / документ готов / сообщение в чат (если оффлайн >5мин) / пропущенный звонок.
- Документы в карточке клиента — пока **только сгенерированные** системой (счета, ТТН, УПД). Загрузка договоров вручную — отложить.

**Принципы.**
- Работаем в `master` (BaltOIL — master only).
- Спека разбита на **5 деплоев**. Каждый деплой независим, тестируется и катится отдельно.
- Все миграции через Alembic, по 1 миграции на деплой.
- Untracked на сервере (`/opt/baltoil/.env`, `/opt/baltoil/tls/`) не трогаем.
- На сервере код в `/opt/baltoil/` (НЕ `/root/BaltOIL/`) — все деплои `git pull` в `/opt/baltoil/`.

---

## Деплой 1 — SMTP-инфраструктура

Объём: ~6 часов Sonnet. Основа для деплоев 4 и 5.

### 1.1 Зависимости и конфиг

**Файлы:**
- `notification_service/pyproject.toml` — добавить `aiosmtplib>=3.0`, `jinja2>=3.1`.
- `notification_service/app/config.py` — новые поля:
  ```python
  smtp_host: str | None = None
  smtp_port: int = 587
  smtp_user: str | None = None
  smtp_password: str | None = None
  smtp_from: str = "noreply@baltoil.ru"
  smtp_use_tls: bool = True
  email_enabled: bool = False  # глобальный kill-switch
  ```
- `notification_service/.env.example` — все 7 ключей.

### 1.2 Email-сервис

**Файлы:**
- `notification_service/app/services/email_service.py` (новый):
  - `async def send_email(to: str, subject: str, body_text: str) -> bool` — возвращает `True/False`, никогда не бросает.
  - Логирует через `logging.getLogger`, метит письма заголовком `X-BaltOIL-Notification`.
  - Если `email_enabled=False` или отсутствует `smtp_host` — логирует "email disabled" и возвращает `False`.
  - Таймаут 10 секунд.

### 1.3 Шаблоны (текстовые)

**Файлы:**
- `notification_service/app/templates/email/order_created.txt`
- `notification_service/app/templates/email/order_claimed.txt`
- `notification_service/app/templates/email/order_in_transit.txt`
- `notification_service/app/templates/email/order_delivered.txt`
- `notification_service/app/templates/email/document_ready.txt`
- `notification_service/app/templates/email/chat_message.txt`
- `notification_service/app/templates/email/call_missed.txt`

Все шаблоны — простой текст, переменные через Jinja2 (`{{ order_number }}`, `{{ client_name }}`, и т.д.). Подпись в конце — "—\nBaltOIL". Без HTML.

### 1.4 Хук в существующий flow нотификаций

**Файлы:**
- `notification_service/app/services/notification_service.py` — в `create_notifications()`:
  - Для каждого получателя — после `db.add(n)` — определить шаблон по `NotificationType`, отрендерить, поставить в `asyncio.create_task(send_email(...))`.
  - Email-адрес тянуть из auth_service: GET `/internal/users/{user_id}/email-target` → возвращает `billing_email` или `user.email`. Эндпоинт создать в `auth_service/app/routers/internal.py`, защитить `X-Internal-Secret`.
  - Если у получателя нет email или `email_enabled=False` — пропустить тихо.

### 1.5 Триггеры "offline >5мин" и "missed call"

**Файлы:**
- `chat_service/app/services/message_service.py` — после публикации в Redis, если у получателя нет активной WS-сессии (Redis-ключ `ws:online:{user_id}` отсутствует или старее 5 мин) — публиковать событие в notification_service со `NotificationType.CHAT_MESSAGE`.
- `chat_service/app/services/ws_manager.py` — при `connect()` ставить `SET ws:online:{user_id} = now EX 300`, при `disconnect()` — `DEL` (если других сессий нет).
- `call_service/app/services/call_service.py` — при `start_call()` если adressee оффлайн (тот же ключ) — публиковать `NotificationType.CALL_MISSED`.

### 1.6 Acceptance

- `docker compose exec notification_service python -c "from app.services.email_service import send_email; import asyncio; asyncio.run(send_email('test@example.com', 't', 'body'))"` → возвращает `True` (или `False` с логом, если SMTP не настроен).
- Создание заявки клиентом → `Notification` в БД + письмо в SMTP-логах.
- Сообщение в чат пользователю, у которого нет активной WS-сессии 5+ минут → письмо ушло.
- Тот же сценарий при активной WS — письма НЕТ.

---

## Деплой 2 — Реквизиты при регистрации + DaData BIK lookup

Объём: ~8 часов Sonnet. Зависит от деплоя 1 только в части `billing_email`-поля (его можно положить и без SMTP).

### 2.1 Расширение DaData-клиента

**Файлы:**
- `auth_service/app/services/dadata_service.py`:
  - Расширить `lookup_by_inn`: добавить в возвращаемый словарь `okved`, `okpo`, `okato`, `fns_status` (active/liquidating/liquidated), `director_name` (из `data.management.name` или `data.fio.full` для ИП).
  - Новая функция `lookup_by_bik(bik: str, api_key: str) -> dict | None` — POST на `https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/bank`. Возвращает `{bank_name, correspondent_account, swift, bank_status, bank_address}`.
  - Таймаут 5с, ошибки → `None`, логирование.

### 2.2 Новые поля в `ClientProfile`

**Файлы:**
- `auth_service/app/models/client_profile.py` — добавить:
  ```python
  okved: Mapped[str | None] = mapped_column(String(20), nullable=True)
  okpo: Mapped[str | None] = mapped_column(String(10), nullable=True)
  okato: Mapped[str | None] = mapped_column(String(11), nullable=True)
  fns_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
  director_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
  swift: Mapped[str | None] = mapped_column(String(11), nullable=True)
  billing_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
  fns_last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
  ```
- `auth_service/alembic/versions/0005_client_extra_fields.py` — `ADD COLUMN IF NOT EXISTS` для всех восьми. Идемпотентно.

### 2.3 Эндпоинт BIK lookup

**Файлы:**
- `auth_service/app/routers/auth.py`:
  - `GET /auth/lookup/bik?bik={9digits}` — без авторизации, rate-limit 10/min (по примеру `/lookup/inn`).
  - Валидация: `bik` ровно 9 цифр.
  - Возвращает 200 `{found: true, data: {...}}` или `{found: false}`. Никаких 500 наружу — DaData недоступна → `{found: false, error: "service_unavailable"}`.

### 2.4 Расширение `/auth/register/company`

**Файлы:**
- `auth_service/app/schemas/user.py` — `CompanyRegisterRequest`:
  - Required: `email`, `password`, `phone`, `full_name` (контактное лицо), `inn`, `bik`, `bank_account`.
  - Optional: `billing_email`, `delivery_address` (адрес доставки — отдельно от юр.адреса).
- `auth_service/app/services/user_service.py` — `register_company()`:
  - После создания `User`, перед созданием `ClientProfile`:
    - Вызвать `lookup_by_inn(inn)` → если результат есть, заполнить `company_name`, `kpp`, `ogrn`, `legal_address`, `okved`, `okpo`, `okato`, `fns_status`, `director_name`.
    - Вызвать `lookup_by_bik(bik)` → если результат есть, заполнить `bank_name`, `correspondent_account`, `swift`.
    - `fns_last_sync_at = now()`.
  - Если DaData недоступна — регистрация всё равно проходит, поля остаются `NULL`, в ответе предупреждение `"fns_lookup_failed": true`.
  - `bank_account` сохранять как есть (валидация: 20 цифр).

### 2.5 Фронтенд: форма регистрации юрлица

**Файлы:**
- `frontend/index.html` — `register-company-form`:
  - Поля в порядке: контактное лицо (full_name), email (для входа), пароль, телефон, ИНН (с blur-триггером `/lookup/inn`), БИК (с blur-триггером `/lookup/bik`), Р/с, billing_email (опционально), адрес доставки (опционально).
  - После успешного lookup по ИНН — показать read-only превью: "Найдено: ООО «Ромашка», ИНН 7707083893, юр.адрес Москва..." с кнопкой "Не то — ввести вручную" (раскрывает скрытые поля для ручного ввода).
  - После успешного lookup по БИК — превью: "Сбербанк, корр.счёт 30101...".
  - При неуспешном lookup — алерт "Не удалось получить данные из ФНС — заполните вручную", показать поля.

### 2.6 Эндпоинт ресинка реквизитов

**Файлы:**
- `auth_service/app/routers/users.py` — `POST /users/{user_id}/fns-resync` (admin only):
  - Заново вызывает DaData по сохранённому ИНН и БИК, апдейтит поля, ставит `fns_last_sync_at = now()`.
  - Audit log с `details={"before": {...}, "after": {...}}`.

### 2.7 Acceptance

- Регистрация юрлица с ИНН 7707083893 + любой БИК → в `ClientProfile` заполнены все поля, `fns_last_sync_at != NULL`.
- Регистрация при выключенной DaData (убрать `DADATA_API_KEY`) → юзер создан, в ответе `fns_lookup_failed: true`, в `ClientProfile` `company_name=NULL`.
- `POST /users/{id}/fns-resync` от админа → DaData дёрнута повторно, поля обновились.
- Клиент с ролью `client` → 403 на ресинке.

---

## Деплой 3 — Карточка клиента (расширение таба)

Объём: ~10 часов Sonnet. Не зависит от 1 и 2 в плане кода (но реальная польза появляется после 2 — данные заполнены).

### 3.1 Новые эндпоинты

**Файлы:**
- `order_service/app/routers/clients.py` (новый или расширение существующего):
  - `GET /clients/{client_id}/documents` — все документы по всем заявкам клиента. Доступ: manager/admin. Параметры: `doc_type?`, `limit=100&offset=0`. Сортировка: `created_at DESC`.
  - `GET /clients/{client_id}/payments` — все платежи + сальдо. Доступ: manager/admin. Возвращает `{payments: [...], total_paid: Decimal, total_due: Decimal, balance: Decimal}`.
  - `GET /clients/{client_id}/summary` — агрегат: count заявок по статусам, общий объём, общая сумма, дата первой/последней заявки.
- `auth_service/app/routers/users.py` — `GET /users/{user_id}/audit?limit=50` — последние записи `audit_log` по конкретному юзеру (admin/manager only).

### 3.2 Фронтенд: модалка карточки клиента

**Файлы:**
- `frontend/index.html`:
  - В таблице клиентов (`tab-clients`) — `onclick` на строку → открывает `<dialog id="client-card-modal">`.
  - Модалка с 5 вкладками внутри: **Реквизиты / Заявки / Документы / Платежи / Аудит**.
  - **Реквизиты** — все поля `ClientProfile` (read-only) + кнопка "Обновить из ФНС" (вызывает `/users/{id}/fns-resync`, только админ).
  - **Заявки** — переиспользует существующий рендер `renderOrders(orders)`, но без таб-навигации.
  - **Документы** — таблица: тип, номер, статус, дата, сумма, кнопки [⬇ Скачать] [💬 В чат] [✉ На почту] (последняя — задизейблить если деплой 5 ещё не катился).
  - **Платежи** — таблица + сальдо в шапке.
  - **Аудит** — последние 50 действий с этим клиентом (изменения тарифа, профиля, ресинки).
- CSS: модалка на 80% ширины, скролл внутри, табы переключаются без перезагрузки данных (lazy-load при первом клике на вкладку).

### 3.3 Acceptance

- Менеджер кликает на клиента в `tab-clients` → открывается модалка с заполненной вкладкой "Реквизиты".
- Переключение на "Документы" → загружаются документы только этого клиента.
- Платежи показывают корректное сальдо (сверить с `payment_service.recompute_and_save`).
- Клиент (роль client) дёргает `/clients/{other_id}/documents` → 403.

---

## Деплой 4 — Экспорт клиентов в xlsx

Объём: ~4 часа Sonnet. Не зависит от 1-3.

### 4.1 Зависимости

**Файлы:**
- `auth_service/pyproject.toml` — добавить `openpyxl>=3.1`.

### 4.2 Эндпоинт

**Файлы:**
- `auth_service/app/routers/users.py`:
  - `POST /clients/export` — body: `{client_ids: list[uuid.UUID]}` (max 1000). Доступ: manager/admin.
  - Стримит xlsx (`StreamingResponse`, content-type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).
  - Колонки в строгом порядке: Тип (юрлицо/физлицо), Наименование, ИНН, КПП, ОГРН, БИК, Банк, Р/с, Корр.счёт, Юр.адрес, Адрес доставки, Тариф, Credit allowed (Да/Нет), Credit limit, Email логин, Billing email, Телефон, Дата регистрации.
  - Лист называется "Клиенты", имя файла `clients_{YYYY-MM-DD}.xlsx`.
  - Audit log: `action=clients.exported, details={count: N}`.

### 4.3 Фронтенд

**Файлы:**
- `frontend/index.html` — в `tab-clients`:
  - Колонка чекбоксов слева в таблице.
  - Кнопка "Экспорт в Excel" над таблицей, disabled пока ничего не выбрано.
  - Onclick — POST `/clients/export`, скачивание файла через `URL.createObjectURL(blob)`.

### 4.4 Acceptance

- Менеджер выбирает 3 клиента, жмёт "Экспорт" → скачивается xlsx с 3 строками + хедер.
- Все 18 колонок заполнены корректно (для ClientProfile с заполненными полями).
- Запрос на 1001 клиента → 400 "too many".
- Запрос от клиента (роль client) → 403.

---

## Деплой 5 — Выставление документов по email

Объём: ~4 часа Sonnet. **Зависит от деплоя 1 (SMTP).**

### 5.1 Эндпоинт

**Файлы:**
- `order_service/app/routers/documents.py`:
  - `POST /orders/{order_id}/documents/{doc_id}/send-email` — body: `{email?: str}`. Доступ: manager/admin.
  - Логика:
    - Если `email` не задан в body → берём `ClientProfile.billing_email`, иначе `User.email`.
    - Валидируем что `Document.status` ∈ {READY, SENT}, file_path не пустой.
    - Читаем PDF с диска, шлём через notification_service POST `/internal/email/send-with-attachment` (новый эндпоинт): `{to, subject, body, attachment: {filename, content_base64, mime_type}}`.
    - При успехе — `Document.status = SENT`, audit log `document.sent_email`.
    - При неуспехе (SMTP down) — 503 "email service unavailable", статус не меняем.

### 5.2 Notification service — email с вложением

**Файлы:**
- `notification_service/app/services/email_service.py` — расширить:
  - `async def send_email_with_attachment(to, subject, body, filename, content_bytes, mime_type) -> bool`.
- `notification_service/app/routers/internal.py` — `POST /internal/email/send-with-attachment` (X-Internal-Secret). Принимает base64-контент, декодирует, шлёт.

### 5.3 Фронтенд

**Файлы:**
- `frontend/index.html` — в карточке клиента → вкладка "Документы" → для каждого документа три кнопки `[⬇] [💬] [✉]`.
  - Onclick `✉` → prompt "Отправить на {billing_email || user.email}? Изменить?" → POST `/orders/{order_id}/documents/{doc_id}/send-email` с опциональным `email` из prompt.
  - Toast при успехе, inline-error при провале.

### 5.4 Acceptance

- Менеджер жмёт "✉" на готовом счёте → клиенту приходит письмо с PDF, тема "Счёт ИНВ-2026-000123 по заявке ORD-2026-000045".
- `Document.status` сменился на `SENT`.
- При SMTP оффлайн → 503, статус документа НЕ изменился.

---

## Порядок исполнения

1. **Деплой 1 (SMTP) — первым.** На прод можно катить даже без работающего SMTP — `email_enabled=False` → ничего не падает.
2. **Деплой 2 (реквизиты).** Параллельно с 1 в части кода, катится после 1 (использует одну миграцию).
3. **Деплой 3 (карточка клиента).** Параллельно с 1-2 в коде, катится после 2 (карточка показывает поля, добавленные в 2).
4. **Деплой 4 (xlsx).** Параллельно с 3.
5. **Деплой 5 (email-документы).** **После 1.**

## Что снаружи спринта

- Загрузка пользовательских документов (договоры, доп.соглашения) — следующий спринт, если потребуется.
- HTML-шаблоны писем — пока plaintext, по запросу заказчика.
- DKIM/SPF/DMARC настройка на домене — отдельная операционная задача, не код.
- Резервные SMTP-провайдеры (failover) — не нужно на этапе MVP.
