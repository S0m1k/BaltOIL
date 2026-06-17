# План: единая сущность «Клиент» + организации (many-to-many)

Статус: черновик плана (код не начат). Ветка: `feature/unified-client-organizations`.
Дата: 2026-06-17.

## Проблема

Сейчас `User(role=client)` связан 1:1 с `ClientProfile`, у которого
`client_type = individual | company`, а реквизиты юрлица лежат прямо на профиле.
Итог: один аккаунт = либо физик, либо **одно** юрлицо. Человек с несколькими
ООО вынужден заводить несколько аккаунтов. Также нет способа дать нескольким
людям доступ к одному юрлицу.

## Решения заказчика (2026-06-17)

1. **Режим заявок**: если у человека есть организации — режим смешанный
   (на каждую заявку выбирает «как физлицо» или конкретную организацию);
   если организаций нет — только как физлицо.
2. **Несколько сотрудников у одного юрлица** — нужна связь many-to-many
   (организация ↔ пользователи), а не владелец 1:1.
3. **Чат «Бухгалтерия»** — один на человека (не на организацию). Совпадает с
   текущей привязкой `client_accountant` к `client_id` — менять привязку не нужно.

## Целевая модель

```
User (аккаунт = человек, role=client)
  ├─ ClientProfile  (1:1) — личность физлица + коммерческие поля для заявок «как физлицо»
  │      delivery_address, passport_*, notes, messenger_blocked, client_number,
  │      tariff_id, credit_allowed, credit_limit, fuel/delivery coef
  │
  └─ OrganizationMember[]  (N) — членство в организациях

Organization (новая таблица)
      реквизиты:  company_name, inn, kpp, ogrn, legal_address,
                  bank_name, bik, bank_account, correspondent_account, swift,
                  contract_number, billing_email, okved/okpo/okato/fns_*, director_name
      коммерч.:   tariff_id, credit_allowed, credit_limit, fuel/delivery coef
      служебн.:   org_number (короткий код, по аналогии с client_number)

OrganizationMember (join, новая таблица)
      organization_id FK, user_id FK
      member_role:  owner | member       # owner правит реквизиты и управляет составом
      UNIQUE(organization_id, user_id)

Order
      client_id        — кто создал заявку (человек), оставляем
      organization_id  — nullable; NULL = «как физлицо», иначе заявка от юрлица
```

Коммерческие поля (тариф/кредит/коэффициенты) живут И на `ClientProfile`
(для заявок физлица), И на `Organization` (для заявок юрлица). `client_context`
резолвит их в зависимости от наличия `organization_id`.

## Ключевые изменения по сервисам

### auth_service
- Модели `Organization`, `OrganizationMember` + миграция (создание таблиц,
  `org_number_seq`).
- Перенос company-полей с `ClientProfile` в `Organization` (поля на профиле
  пока оставить nullable «для отката», удалить отдельной миграцией позже).
- CRUD организаций: создать (через DaData по ИНН), читать свои, править
  (только owner / admin), архивировать.
- Управление составом: добавить участника по телефону (см. «Открытые вопросы»),
  сменить роль, убрать. Доступ — owner организации или admin.
- Internal context-эндпоинт: `GET /internal/clients/{id}/context` принимает
  опциональный `organization_id`; при наличии — отдаёт коммерческий контекст
  организации (с проверкой членства), иначе — профиля физлица.
- DaData-ресинк переносится на уровень организации.

### order_service
- `Order.organization_id` (nullable) + миграция; backfill историческим заявкам.
- Создание заявки принимает `organization_id`; валидируем, что заявитель —
  участник этой организации (через auth internal).
- `client_context.py`: ключ (client_id, organization_id); резолв тарифа/кредита/
  типа оплаты из организации либо из профиля.
- Buyer-snapshot и документы (счёт, УПД, ТТН, договор, доверенность) берут
  реквизиты из организации для юр-заявок; снапшот фиксируется на момент создания,
  чтобы старые документы не «поплыли» при правке реквизитов.
  ⚠️ Учесть известный баг internal-пути auth (см. `baltoil-internal-api-path-bug`).

### chat_service
- Привязку `client_accountant` к `client_id` не меняем (один чат на человека).
- Правило показа: предлагать чат «Бухгалтерия» клиенту, у которого есть хотя бы
  одна организация (или всем — уточнить).

### frontend
- Регистрация упрощается: все регистрируются как человек (физлицо).
- Раздел «Мои организации»: добавление по ИНН (DaData), реквизиты, состав
  сотрудников (для owner).
- Создание заявки: селектор «Физлицо / Организация …» (показывается, только если
  у пользователя есть организации).
- Экраны реквизитов и документов — на уровень организации.

## Миграция данных (1:1, безопасно)

Сегодня company-клиент = 1 user = 1 компания, поэтому перенос однозначен:
1. Для каждого `ClientProfile.client_type == company`:
   - создать `Organization` из его company- и коммерческих полей;
   - создать `OrganizationMember(user, org, role=owner)`;
   - проставить `organization_id` всем заявкам этого клиента.
2. `individual`-профили не трогаем (organization_id = NULL).
3. Документы прошлых заявок не трогаем — у них собственный snapshot.

## Поэтапный раскат

- **Фаза 0** — ветка, этот план, аудит данных на проде (сколько company-профилей,
  заявок у них).
- **Фаза 1 (auth)** ✅ КОД ГОТОВ — таблицы Organization/Member, CRUD, членство,
  context с org_id; backfill-миграция company → org + owner.
  Файлы: models/organization.py, schemas/organization.py,
  services/organization_service.py, routers/organizations.py,
  alembic 0010_organizations.py; internal context/buyer-snapshot/legal-profile
  принимают organization_id; link_pending_invites в регистрации.
  ⏳ Интеграционная проверка (alembic upgrade 0010 + старт сервиса) — нужен Docker.
- **Фаза 2 (order)** ✅ КОД ГОТОВ + ПРОВЕРЕН на Docker — Order.organization_id
  (миграция 0018, без backfill, NULL=физлицо/legacy), создание с organization_id
  (членство через auth context, 400 если не участник), client_context по org,
  документы/buyer-snapshot из организации, договор per-organization
  (Contract.organization_id), видимость member = все заявки организации
  (auth /internal/users/{id}/organization-ids). Деплой order + auth.
- **Фаза 3 (frontend)** ✅ КОД ГОТОВ — селектор «Оформить от имени» в создании
  заявки (organization_id в create+preview), вкладка «Мои организации» (список,
  создание по ИНН, состав сотрудников), регистрация только как физлицо
  (юрлица добавляются после входа). JS syntax-clean, прокси проверен;
  полный браузерный клик-через не гонялся.
- **Фаза 4 (chat)** ✅ КОД ГОТОВ — чат «Бухгалтерия» доступен клиенту с ≥1
  организацией (вместо client_type=company): chat_service ensure-client-accountant
  гейтит по auth /internal/users/{id}/organization-ids (auth_client.get_organization_ids).
  Фильтры видимости не трогаем — они лишь включают существующие чаты.
- **Чистка (отложено)** — удаление устаревших company-полей с ClientProfile и
  мёртвого register/company ПОСЛЕ ≥1 недели стабильной работы на проде.

Каждая фаза самостоятельно деплоится и обратносовместима: пока фронт не обновлён,
`organization_id` везде nullable и поведение = «как физлицо/как раньше».

## Решённые вопросы (2026-06-17)

1. **Добавление сотрудника**: owner добавляет по номеру телефона; если аккаунта
   нет — pending-приглашение, активируется при регистрации. Admin тоже может.
2. **Права**: member создаёт заявки от организации и видит её документы; править
   реквизиты и состав — только owner/admin.
3. **Тариф/кредит физлица**: остаются на ClientProfile; заявки «как физлицо»
   считаются по нему.
4. **Видимость заявок организации**: member видит ВСЕ заявки своей организации
   (общий учёт по юрлицу) — реализуется в Фазе 2 (order_service).
