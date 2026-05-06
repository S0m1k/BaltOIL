# BaltOIL — Архитектура системы

## Обзор

BaltOIL — платформа управления заказами на доставку топлива. Система построена как набор независимых микросервисов на Python/FastAPI, общающихся через HTTP и Redis Pub/Sub.

```
┌─────────────────────────────────────────────────────────┐
│                      Frontend (nginx)                    │
│                     http://host:8080                     │
│        SPA на чистом JS — один index.html               │
└──────────────┬─────────────────────────────────────────┘
               │ HTTP / WebSocket / SSE
       ┌───────┼────────────────────────────────┐
       │       │                                │
  :8001│  :8002│  :8003│  :8004│  :8005│        │
  Auth │ Order │Delivery│ Chat  │Notif  │        │
       │       │        │       │       │        │
       └───────┴────────┴───────┴───────┘        │
               │         (все сервисы)           │
       ┌───────┴───────────────────────┐         │
       │        PostgreSQL :5432       │         │
       │  (отдельная БД на сервис)     │         │
       └───────────────────────────────┘         │
       ┌───────────────────────────────┐         │
       │          Redis :6379          │         │
       │  Pub/Sub + WebSocket broker   │─────────┘
       └───────────────────────────────┘
```

---

## Сервисы

### 1. `auth_service` — порт 8001
Управление пользователями, аутентификация, JWT.

**БД:** `baltoil_auth`

**Роли пользователей:**
| Роль | Описание |
|------|----------|
| `admin` | Полный доступ ко всему |
| `manager` | Управление заявками и клиентами |
| `driver` | Создание рейсов, выполнение доставок |
| `client` | Создание заявок на топливо |

**Ключевые эндпоинты:**
```
POST /api/v1/auth/register/individual  — Регистрация физлица
POST /api/v1/auth/register/company     — Регистрация юрлица
POST /api/v1/auth/login                — Вход, получение токенов
POST /api/v1/auth/refresh              — Обновление access token
POST /api/v1/auth/logout               — Отзыв refresh token
GET  /api/v1/users/me                  — Текущий пользователь
POST /api/v1/users/me/change-password  — Смена пароля
GET  /api/v1/users                     — Список пользователей (manager+)
POST /api/v1/users                     — Создать пользователя (admin)
```

**Токены:**
- `access_token` — JWT, срок 30 минут, содержит `sub` (user_id), `role`, `name`
- `refresh_token` — случайный UUID, хранится в БД (hash SHA-256), ротируется при обновлении
- Единый `JWT_SECRET_KEY` на все сервисы — сервисы верифицируют токен локально без обращения к auth_service

**Модели:**
- `User` — пользователь (email, hashed_password, full_name, role, is_active, is_archived)
- `ClientProfile` — профиль клиента (тип: физлицо / юрлицо, паспорт, ИНН, реквизиты)
- `RefreshToken` — refresh токен (token_hash, user_id, expires_at, is_revoked)
- `AuditLog` — лог действий (actor_id, action, entity_type, entity_id, ip_address)

---

### 2. `order_service` — порт 8002
Заявки на доставку топлива — основной бизнес-процесс.

**БД:** `baltoil_orders`

**Жизненный цикл заявки:**
```
NEW → IN_PROGRESS → ASSIGNED → IN_TRANSIT → DELIVERED
                              └→ PARTIALLY_DELIVERED → ASSIGNED (повтор)
    └→ REJECTED (любой менеджер/админ из NEW или IN_PROGRESS)
```

**Ключевые эндпоинты:**
```
POST   /api/v1/orders              — Создать заявку
GET    /api/v1/orders              — Список заявок (с фильтрами)
GET    /api/v1/orders/{id}         — Детали заявки
PATCH  /api/v1/orders/{id}         — Обновить (приоритет, водитель, комментарий)
POST   /api/v1/orders/{id}/status  — Сменить статус (с валидацией машины состояний)
DELETE /api/v1/orders/{id}         — Архивировать заявку
GET    /api/v1/fuel-types          — Доступные типы топлива
```

**Правила видимости:**
| Роль | Что видит |
|------|-----------|
| `client` | Только свои заявки |
| `driver` | Свои + свободные IN_PROGRESS/ASSIGNED (биржа заявок) |
| `manager` / `admin` | Все заявки |

**Модели:**
- `Order` — заявка (order_number, client_id, fuel_type, volume_requested, volume_delivered, status, driver_id, manager_id, payment_type, priority)
- `OrderStatusLog` — история переходов статусов
- `OrderYearCounter` — атомарный счётчик для генерации order_number

**Redis:** Публикует события в канал `events:orders` при создании и смене статуса:
```json
{
  "event": "order_created" | "order_status",
  "order_id": "...",
  "client_id": "...",
  "driver_id": "...",
  "status": "...",
  "title": "...",
  "body": "..."
}
```

---

### 3. `delivery_service` — порт 8003
Рейсы (trips), транспортные средства, отчёты водителей.

**БД:** `baltoil_delivery`

**Жизненный цикл рейса:**
```
PLANNED → IN_TRANSIT → COMPLETED
        └→ CANCELLED
```

**Ключевые эндпоинты:**
```
POST  /api/v1/trips              — Создать рейс (driver/manager)
GET   /api/v1/trips              — Список рейсов
GET   /api/v1/trips/{id}         — Детали рейса
POST  /api/v1/trips/{id}/start   — Начать рейс (водитель)
POST  /api/v1/trips/{id}/complete — Завершить рейс (водитель)
POST  /api/v1/trips/{id}/cancel  — Отменить рейс
GET   /api/v1/vehicles           — Список ТС
POST  /api/v1/vehicles           — Добавить ТС (admin)
GET   /api/v1/reports/driver     — Отчёт водителя за период
```

**Модели:**
- `Trip` — рейс (order_id, driver_id, vehicle_id, volume_planned, volume_actual, odometer_start/end, status)
- `Vehicle` — транспортное средство (plate, model, capacity_liters, assigned_driver_id)

---

### 4. `chat_service` — порт 8004
Внутренний чат между участниками процесса. Realtime через WebSocket.

**БД:** `baltoil_chat`

**Типы чатов:**
| Тип | Участники |
|-----|-----------|
| `client_support` | Клиент ↔ Менеджер |
| `internal` | Менеджер ↔ Водитель |

**Ключевые эндпоинты:**
```
POST /api/v1/conversations             — Создать беседу
GET  /api/v1/conversations             — Список бесед
GET  /api/v1/conversations/{id}/messages — История сообщений
WS   /ws/{conv_id}?token=<jwt>         — WebSocket подключение
```

**Redis:** Канал `chat:{conv_id}` — бродкаст сообщений всем подключённым к беседе. Публикует события в `events:chat` для notification_service.

**Модели:**
- `Conversation` — беседа (type, is_archived, participants)
- `ConversationParticipant` — участник (conversation_id, user_id)
- `Message` — сообщение (conversation_id, sender_id, sender_role, sender_name, text)

---

### 5. `notification_service` — порт 8005
Хранение и доставка уведомлений в реальном времени через SSE.

**БД:** `baltoil_notifications`

**Ключевые эндпоинты:**
```
GET  /api/v1/notifications              — Список уведомлений пользователя
POST /api/v1/notifications/{id}/read    — Прочитать уведомление
POST /api/v1/notifications/read-all     — Прочитать все
GET  /api/v1/notifications/stream       — SSE поток (token в query param)
POST /api/v1/notifications/internal/publish — Внутренний push (X-Internal-Secret)
```

**Типы уведомлений:** `order_created`, `order_status`, `chat_message`, `trip_assigned`, `trip_status`

**Поток данных:**
```
order_service ──publish──► events:orders ──► notification_service subscriber
chat_service  ──publish──► events:chat   ──► notification_service subscriber
                                                        │
                                                        ▼
                                            INSERT INTO notifications
                                                        │
                                                        ▼
                                            PUBLISH notifs:{user_id}
                                                        │
                                                        ▼
                                            SSE stream → браузер
```

---

## Инфраструктура

### Docker Compose

```
Service              Port      Notes
─────────────────────────────────────────────
postgres             127.0.0.1:5432  localhost only
redis                127.0.0.1:6379  localhost only, no auth
auth_service         0.0.0.0:8001
order_service        0.0.0.0:8002
delivery_service     0.0.0.0:8003
chat_service         0.0.0.0:8004
notification_service 0.0.0.0:8005
frontend (nginx)     0.0.0.0:8080
```

### БД на старте

PostgreSQL инициализируется скриптом `postgres-init/01-create-databases.sh`:
```
baltoil_auth
baltoil_orders
baltoil_delivery
baltoil_chat
baltoil_notifications
```

Каждый сервис вызывает `Base.metadata.create_all` при старте — таблицы создаются автоматически.

### Redis

| Канал | Назначение |
|-------|-----------|
| `chat:{conv_id}` | Бродкаст сообщений чата |
| `events:orders` | События заказов для notification_service |
| `events:chat` | События чата для notification_service |
| `notifs:{user_id}` | Push уведомления конкретному пользователю |

Разные БД Redis (0–3) для разных сервисов во избежание коллизий ключей.

---

## Безопасность

- **JWT** — HS256, 30 минут. Секрет единый (`JWT_SECRET_KEY`) для всех сервисов.
- **Refresh tokens** — хранятся как SHA-256 hash, ротируются при обновлении, отзываются при смене пароля.
- **CORS** — явный whitelist через `ALLOWED_ORIGINS` env (по умолчанию `http://localhost:8080`).
- **Rate limiting** — slowapi на login (20/мин) и register (10/мин).
- **Internal API** — `/internal/publish` защищён `X-Internal-Secret` header.
- **Postgres/Redis** — биндятся только на localhost в dev, не доступны из LAN.

---

## Конфигурация (.env)

Каждый сервис использует `.env` файл (не коммитится в git). Ключевые переменные:

| Переменная | Где используется |
|-----------|-----------------|
| `DATABASE_URL` | Все сервисы |
| `JWT_SECRET_KEY` | Все сервисы (должен быть одинаковым) |
| `REDIS_URL` | order, chat, notification |
| `ALLOWED_ORIGINS` | Все сервисы (CORS) |
| `BOOTSTRAP_ADMIN_EMAIL/PASSWORD` | auth_service (первый запуск) |
| `INTERNAL_API_SECRET` | notification_service |

---

## Структура проекта

```
BaltOIL/
├── auth_service/
│   ├── app/
│   │   ├── core/         # JWT, security, зависимости, исключения
│   │   ├── models/       # SQLAlchemy ORM модели
│   │   ├── routers/      # FastAPI роутеры
│   │   ├── schemas/      # Pydantic схемы
│   │   ├── services/     # Бизнес-логика
│   │   ├── config.py
│   │   ├── database.py
│   │   └── main.py
│   ├── Dockerfile
│   └── requirements.txt
├── order_service/         # Аналогичная структура
├── delivery_service/      # Аналогичная структура
├── chat_service/          # Аналогичная структура
├── notification_service/  # Аналогичная структура
├── frontend/
│   └── index.html         # SPA — всё в одном файле
├── postgres-init/
│   └── 01-create-databases.sh
├── docker-compose.yml
└── ARCHITECTURE.md
```

---

## Запуск

```bash
# Первый запуск
docker compose up -d

# Пересобрать конкретный сервис
docker compose up -d --build auth_service

# Логи
docker compose logs -f auth_service

# Подключиться к БД
psql -h 127.0.0.1 -U postgres baltoil_auth
```

После запуска доступно:
- **UI**: http://localhost:8080
- **Auth API docs**: http://localhost:8001/docs
- **Order API docs**: http://localhost:8002/docs

Первый admin создаётся автоматически из `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD`.

---

## Что не реализовано (планируется)

- **Учёт топлива** — нет модуля управления складом/резервуарами. Нет прихода/расхода/остатка. При доставке `volume_delivered` записывается в заявку, но со склада ничего не списывается. Требует отдельного сервиса или модуля.
- **Ценообразование** — нет полей `price_per_liter`, `total_amount`, `payment_status`.
- **Email-верификация** — регистрация без подтверждения email.
- **Сброс пароля** — нет механизма "забыл пароль".
- **Мультитенантность** — система рассчитана на одну компанию.
