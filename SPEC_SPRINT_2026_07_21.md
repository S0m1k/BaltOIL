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

---
---

# Часть 2 — Правки вечера 2026-07-21 (задеплоено, master 66b4dee / mobile 59d19c1)

## Ф3 — Перерегистрация с данными удалённого пользователя

**Проблема (репорт заказчика).** Удалил пользователя → не смог зарегистрироваться
заново с тем же телефоном: «Пользователь с таким номером уже существует».
Причина: `users.email` / `users.phone` под **unique-индексами БД**, а архивная
строка (`is_archived=true`) их не освобождала. Аналогично ИНН юрлица блокировался
app-проверкой `_check_inn_unique` без фильтра по архивным.

**Решение.**
- `archive_user`: перед архивацией `email → NULL`, `phone → NULL`; оригиналы
  сохраняются в `audit_log` (action `user.archived`, details `{email, phone}`).
  Логин архивного невозможен и раньше (NULL не находится), история заявок
  привязана по `user_id` — снапшоты не страдают.
- `_check_inn_unique`: JOIN на `users`, профили архивных владельцев ИНН не блокируют.
- **Backfill на проде выполнен**: единственная архивная строка с занятым номером
  (+79818865585) освобождена, оригиналы в audit_log (action `user.archived.backfill`).

## Ф4 — Удаление конкретного сообщения в чате

- Бэкенд был (`DELETE /conversations/{conv_id}/messages/{msg_id}` → soft-delete
  `is_archived=true`; право: автор сообщения или менеджер/админ). Добавлено:
  publish `{"event":"message_deleted","message_id",...}` в Redis `chat:{conv_id}`.
- Веб: кнопка «Удалить» (красная) в действиях сообщения (Ответить / Закрепить /
  Удалить) — видна автору и менеджеру/админу; `confirm()` → DELETE → пузырь
  убирается локально; у остальных участников — по WS-событию `message_deleted`.
  Панель закреплённых обновляется (удалили закреплённое — оно уходит из панели).

## Ф5 — Мобильный масштаб веба («чуть отдалить»)

Весь интерфейс на телефоне казался слишком крупным. В `@media (max-width: 768px)`:
- `body { zoom: 0.85 }` — равномерное уменьшение на 15%.
- **Готча:** `zoom` НЕ масштабирует vh/dvh-единицы → все полноэкранные высоты
  компенсированы делением: `min-height: calc(100vh / 0.85)` (body, #app-screen,
  .auth-wrap), `.burger-drawer { height: calc(100dvh / 0.85) }`,
  `.chat-shell { height: calc(100vh / 0.85 - 56px - 56px) }`.
  Новые полноэкранные vh-стили в мобильном media query — тоже делить на 0.85.

## Ф6 — Новый пользователь (прод, выполнено)

Сомов Андрей Андреевич, **role=admin**, phone 89818865585, somov.15.06@mail.ru —
создан скриптом в auth-контейнере (в UI-форме создания нет роли admin), пароль
по схеме существующих staff-аккаунтов, вход проверен (HTTP 200 + access_token).
Аудит: `user.created_by_admin` (details.via = deploy-script 2026-07-21).

---

# Часть 3 — Мобильное приложение: баги звонков (СДЕЛАНО 2026-07-21 вечером, mobile c9f5313/fdde41e)

## З1 — Звук пропадает, когда телефон уходит в спящий режим

**Репорт:** «во время разговора по телефону в приложении телефон уходит в спящий
режим, и пока его не разблокируешь — звук пропадает».

**Диагноз.** В `pubspec.yaml` нет wakelock-пакета; экран звонка не держит
устройство активным, Android усыпляет процесс вместе с аудиопотоком LiveKit
(нет foreground service на время звонка).

**Что сделать (call_screen.dart + android):**
1. `wakelock_plus`: `WakelockPlus.enable()` при входе в звонок,
   `disable()` при завершении — экран не гаснет во время разговора.
2. Android foreground service на время активного звонка:
   `foregroundServiceType="microphone|mediaPlayback"` (manifest) — аудио живёт
   даже при погашенном экране/сворачивании. LiveKit SDK умеет
   (`livekit_client` audio session/foreground service опции).
3. iOS: `UIBackgroundModes: audio, voip` в Info.plist.

## З2 — У водителя не звонит входящий («я звонил водителю — у него не было звонка»)

**Репорт + вопрос «где его включить?».** Ответ: это не настройка — сейчас
входящий звонок обнаруживается **только при открытом приложении** (поллинг
`/calls/active` раз в 4 с; пуш `call_initiated` лишь ускоряет поллинг в
форграунде). Приложение свёрнуто/закрыто → звонка нет. Включить негде — нужно
доделать код.

**Что сделать:**
1. Довести обвязку `flutter_callkit_incoming` (пакет уже в pubspec ^3.1.3,
   `callkit_service.dart` начат, НЕ закоммичен): по FCM data-пушу
   `call_initiated` показывать системный экран входящего звонка
   (`FlutterCallkitIncoming.showCallkitIncoming`) — работает в фоне и при
   закрытом приложении, со звонком и вибрацией.
2. FCM: `call_initiated` должен идти **data-пушом с high priority**
   (notification_service/push_service), иначе Android дросселирует в Doze.
3. «Принять» из системного экрана → deep-link в CallScreen с call_id;
   «Отклонить» → `POST /calls/{id}/decline`.
4. Проверить у водителя: разрешение на уведомления, канал со звуком,
   отключённую оптимизацию батареи (Xiaomi/Huawei агрессивно убивают фон).
5. iOS полноценно — только через VoIP-пуши (PushKit) + Apple Developer аккаунт
   (его пока нет — см. [FCM/пуши]); Android закрывается пп. 1–3.

## Реализация части 3 (сделано)

**З1:** `wakelock_plus` — WakelockPlus.enable() в initState CallScreen /
disable() в dispose: экран не гаснет, аудио LiveKit живёт весь звонок.

**З2:** доделана обвязка callkit:
- `callkit_service.dart` — системный экран входящего (flutter_callkit_incoming),
  accept → GET /calls/{id} → token → CallScreen; decline → /calls/{id}/end;
- `push_registrar.dart` — top-level `firebaseBackgroundHandler`
  (@pragma vm:entry-point): показывает callkit-экран из data-пуша даже при
  убитом приложении; тот же экран в форграунде (onMessage);
- `push_service.py` — call_initiated шлётся **data-only + high priority**
  (хотфикс прода 2026-07-18 закоммичен) + `schedule_pushes(extra_data)`:
  в data теперь call_id/room_name/initiated_by_name — имя звонящего на экране
  и подключение без запроса к API (задеплоено, master 4cc1190);
- поллер `incoming_call_watcher` остаётся страховкой, дедуп по активным
  callkit-звонкам.

**Бонус (parity части 1, тоже сделано в mobile):**
- галочки-статусы в чате: sent/delivered/read из `MessageResponse.status` +
  realtime `read_receipt` по WS + опрос-страховка (5 с);
- «Удалить» сообщение (long-press bottom-sheet; автор/менеджер/админ) + WS
  `message_deleted` убирает пузырь у всех;
- событийные WS-кадры (`message_pinned`/`conversation_deleted`/…) больше не
  роняют обработчик чата — раньше ChatMessage.fromJson падал на них.

**Проверить на устройстве водителя:** разрешение на уведомления, автозапуск/
отключение оптимизации батареи (Xiaomi/Huawei), иначе система может резать
даже high-priority data-пуши. iOS — по-прежнему ждёт Apple Developer (PushKit).

## Статус спек за 2026-07-21
- Часть 1 (утро): удаление юзера + галочки — **задеплоено** (master b4adaaa).
- Часть 2 (вечер): перерегистрация, удаление сообщений, масштаб, новый админ —
  **задеплоено** (master 66b4dee).
- Часть 3: звонки мобилки + parity чата — **сделано** (mobile c9f5313 + fdde41e,
  бэкенд пушей задеплоен master 4cc1190); нужен новый APK на устройства.
