# SPEC — Правки 2026-07-21 (удаление пользователя админом + галочки-статусы сообщений)

**Контекст.** Заказчик попросил две доработки:
1. Дать администратору возможность **удалять пользователя после деактивации**.
2. Добавить в чат **галочки-статусы у сообщений** (доставлено / прочитано), как в мессенджерах.

**Ветка.** Реализовано на общих сервисах (`auth_service`, `chat_service`, `frontend`) —
код идентичен между `master` и `mobile`. Задеплоено на прод из `master`; на `mobile`
лежит тот же код (для parity мобильного приложения).

---

## Фича 1 — Удаление пользователя админом после деактивации

**Правило.** Активного пользователя удалить нельзя — сначала «Деактивировать»
(`is_active=false`), затем появляется кнопка «Удалить». Защита от удаления
работающего аккаунта одним кликом.

**Удаление = мягкое (soft-delete).** Используется уже существующий эндпоинт
`DELETE /api/auth/users/{id}` → `archive_user`: ставит `is_archived=true`,
`is_active=false`, отзывает активные токены, пишет `audit_log`. Аккаунт пропадает
из всех списков (`list_users` фильтрует `is_archived==false`). **Хард-делит НЕ делаем** —
FK на заявки/аудит/сообщения (снапшоты) остались бы битыми; история сохраняется.

### Бэкенд
- `auth_service/app/services/user_service.py::archive_user` — добавлена проверка:
  ```python
  if user.is_active:
      raise ForbiddenError("Сначала деактивируйте пользователя, затем удалите")
  ```
  (плюс существующая защита «нельзя архивировать самого себя»).
- Эндпоинт `DELETE /users/{user_id}` уже был (admin-only), UI его раньше не вызывал.
- Миграций в auth нет.

### Фронтенд (`frontend/index.html`)
- `renderUsersTable` — у **неактивного** пользователя рядом с «Активировать»
  выводится красная кнопка «Удалить» (только для роли admin).
- `deleteUser(userId)` — `confirm()` с именем из `_allUsers`, затем
  `DELETE ${AUTH_URL}/users/{id}`, тост, `loadUsers()`.

### Крайние случаи
- Попытка удалить активного (гонка UI) → 403 с понятным сообщением.
- Самоудаление админа → 403.

---

## Фича 2 — Галочки-статусы сообщений (доставлено / прочитано)

**Модель статуса.** У своих сообщений отправитель видит один из трёх статусов:
- `sent` — `✓` (отправлено, лежит на сервере);
- `delivered` — `✓✓` серые (долетело до устройства получателя);
- `read` — `✓✓` синие `#34b7f1` (получатель открыл диалог).

Статус — **только для своих сообщений**; у чужих `status = null`.
В групповом чате критерий = «хотя бы один другой участник» (осознанное упрощение).

### Данные
- **chat миграция `0006_delivery_receipts_2026_07_21`** — новая колонка
  `conversation_participants.last_delivered_at TIMESTAMPTZ NULL` (идемпотентная).
  Уже существующий `last_read_at` = момент прочтения.
- Модель `ConversationParticipant.last_delivered_at`.

### Когда ставится `delivered`
`last_delivered_at = now()` для участника, когда он заведомо получил сообщения:
- открыл список чатов — `list_conversations` → `touch_delivered_bulk` (один UPDATE по всем его диалогам);
- открыл диалог — `get_messages` → `touch_delivered`;
- подключился по WebSocket — `websocket_endpoint` → `touch_delivered`;
- прочитал — `mark_read` (read ⇒ delivered, не откатываем более свежий назад).

### Когда ставится `read`
`mark_read` (POST `/conversations/{id}/read`) — как и раньше; фронт зовёт его при
открытии диалога, при приходе чужого сообщения в открытый чат и при отправке.

### Вычисление статуса
- `get_peer_watermarks(conv_id, actor_id)` → `MAX(last_read_at)`, `MAX(last_delivered_at)`
  среди **других** участников.
- `compute_message_status(msg, actor_id, peer_read_at, peer_delivered_at)`:
  `created_at <= peer_read_at` → `read`; иначе `<= peer_delivered_at` → `delivered`; иначе `sent`.
- Отдаётся в `MessageResponse.status` (эндпоинт `GET /conversations/{id}/messages`).

### Realtime
- `mark_read` публикует в Redis `chat:{conv_id}`:
  `{"event":"read_receipt","conversation_id","user_id","read_at"}`.
- Фронт (`ws.onmessage`) → `markMessagesRead(read_at)`: красит свои `.msg-row.mine`
  с `data-created <= read_at` в синие `✓✓`. Своё же событие игнорируется (`user_id != me`).
- **`delivered` в реальном времени НЕ рассылается** (чтобы не спамить Redis на каждый
  поллинг списка) — серые двойные галочки подтягиваются при следующей загрузке диалога.

### Фронтенд (`frontend/index.html`)
- `msgStatusHTML(m)` — рендер `✓` / `✓✓` / синие `✓✓` (+ `title`), только для своих.
- `.msg-row` получил `data-created` (для сравнения при read_receipt).
- CSS `.msg-status` / `.msg-status.read`.
- Оптимистичная отправка: POST-ответ без метки → трактуется как `sent`.

### API-совместимость
- Новое поле `status` в `MessageResponse` необязательное — старых клиентов и
  мобильное приложение не ломает (лишнее поле в JSON игнорируется).

---

## Деплой (выполнен 2026-07-21)

Оба сервиса bind-mount'ят исходники + `entrypoint.sh` делает `alembic upgrade head`.
Пересборка не нужна (новых зависимостей нет):

```
cd /opt/baltoil && git pull
docker compose restart chat_service auth_service   # chat_service авто-мигрирует до 0006
# frontend — bind-mount, index.html подхватывается сразу
```

Проверка: `alembic current` в chat_service = 0006; health сервисов; ручной прогон
удаления деактивированного юзера и обмена сообщениями между двумя ролями.

## Мобильное приложение (parity, TODO при желании)
Бэкенд уже отдаёт `MessageResponse.status` и рассылает `read_receipt`. Для 1-в-1
с вебом в Flutter-приложении осталось:
- парсить `status` в `chat_models.dart` и рисовать галочки в бабле отправителя;
- обрабатывать событие `read_receipt` в WS-обработчике чата;
- (опц.) кнопка «Удалить» в админ-разделе пользователей, если он есть в мобилке.
