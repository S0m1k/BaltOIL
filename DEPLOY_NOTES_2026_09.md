# Деплой спринта 2026-09

Что перезапускать после `git pull` на проде (`/opt/baltoil`). Миграций в спринте нет.
`frontend` — статика в nginx: перезапуск не нужен, достаточно `git pull`
(жёсткий refresh в браузере из-за кэша).

| Пункт | Что менялось | Деплой |
|-------|--------------|--------|
| П1 | frontend/index.html (заявка «От организации») | только `git pull`, force-recreate не нужен |
| П2 | order_service (`kind` в `/finance/*`, `order_kind` в internal `/driver-orders`) + delivery_service (отчёт водителя) + frontend | force-recreate `order_service`, затем `delivery_service` (см. ниже) |
| П3 | order_service (query `kind` в `/orders` и `/orders/counts`) + frontend | `docker compose up -d --force-recreate --no-deps order_service` |
| П4 | order_service (`DELETE /orders/{id}/hard`), delivery_service + chat_service (новые подписчики `events:orders`), notification_service + frontend | force-recreate всех четырёх сервисов (см. ниже) |
| П5 | order_service (`money.price_first_breakdown`: цена за литр первична, итог с копейками) | `docker compose up -d --force-recreate --no-deps order_service` |
| П6 | order_service (гейт отгрузки, payment-options, дефолт DEBT) + frontend | `docker compose up -d --force-recreate --no-deps order_service` |
| П7 | order_service (клиенту не отдаётся `manager_comment`) + frontend (подписи полей) | `docker compose up -d --force-recreate --no-deps order_service` |
| П8 | order_service (гейт правки закрытых заявок) + frontend (карандаши комментариев и контакта) | `docker compose up -d --force-recreate --no-deps order_service` |
| П9 | order_service (адрес обязателен только клиенту) + frontend (валидация по роли, «Адрес уточняется») | `docker compose up -d --force-recreate --no-deps order_service` |
| П10 | order_service (тип формулы `equal`) + frontend (пункт «= базовый») | `docker compose up -d --force-recreate --no-deps order_service` |
| П11 | кода нет — «166 ОТК» уже работает, номер внутри PDF оставлен по решению заказчика | деплой не нужен, задачу на доске закрыть |

## П4 — полное удаление заявки админом

```
docker compose up -d --force-recreate --no-deps order_service
docker compose up -d --force-recreate --no-deps delivery_service
docker compose up -d --force-recreate --no-deps chat_service
docker compose up -d --force-recreate --no-deps notification_service
```

Проверка после деплоя:
- в логах `delivery_service` и `chat_service` при старте есть строка `Subscribed to ['events:orders']`;
- удаление тестовой доставленной заявки админом даёт в ответе `stock_restored_l`, а остаток
  топлива в разделе «Склад» вырастает ровно на этот объём (остаток — хранимое поле
  `fuel_stock.current_volume`, возвращается компенсирующей дельтой при удалении проводок);
- в логах `order_service` появляется `action=order.hard_deleted`, в delivery/chat/notification —
  соответствующие `action=order.hard_deleted.*_cleanup`.

Если Redis был недоступен в момент удаления, событие теряется (pub/sub без персистентности):
рейсы/чат/уведомления заявки останутся сиротами. Лечится вручную; повторной отправки события нет.

## П5 — цена за литр первична

Суммы заявок больше не целые рубли. Уже выпущенные счета не перевыпускаются автоматически —
новые и перевыпущенные будут с копейками.

## П2 — отчёты по видам заявок

Порядок: сначала `order_service`, потом `delivery_service` — отчёт водителя ждёт `order_kind`
от internal-эндпоинта (поле с дефолтом `""`, поэтому обратный порядок не ломает, просто все
заявки временно попадут в секцию «Прочие»).

## Ветка `mobile` (П12–П14)

Бэкенд не менялся. Пересобрать и выложить APK из `mobile@c05d118`: единое окно доставки
физлицу (CRM-38), адрес необязателен водителю, плюс уже готовые фиксы «назначенная заявка
не видна» и «карточка не открывается» (5984001).
