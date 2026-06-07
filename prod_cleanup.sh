#!/usr/bin/env bash
#
# Очистка прод-данных до состояния «одна тестовая заявка».
# Запускать НА ПРОД-СЕРВЕРЕ из /opt/baltoil ПОСЛЕ:
#   1) git pull + миграции + restart auth/chat
#   2) seed_staff.py (8 пользователей)
#   3) prod_test_state.py (создаёт тест-юрлицо + 1 заявку с документами)
#
# Берёт TEST_ORDER_ID / TEST_CLIENT_ID из вывода prod_test_state.py:
#   TEST_ORDER_ID=... TEST_CLIENT_ID=... bash prod_cleanup.sh
#
# Делает (ПОСЛЕ pg_dump всех БД):
#   - orders:   удаляет все заявки кроме тестовой (каскадом — документы/платежи/логи)
#   - contracts: удаляет договоры всех клиентов кроме тестового юрлица
#   - fuel_transactions: оставляет только операции тестовой заявки (расход по заявке
#                        + приход с меткой TESTSETUP), склад пересчитывает
#   - users:    ДЕАКТИВИРУЕТ (is_active=false, архив) всех, кроме 8 seed + тест-юрлица
#               (НЕ удаляет — обратимо)
#
set -euo pipefail

: "${TEST_ORDER_ID:?нужно задать TEST_ORDER_ID (из prod_test_state.py)}"
: "${TEST_CLIENT_ID:?нужно задать TEST_CLIENT_ID (из prod_test_state.py)}"
ARRIVAL_MARK="${ARRIVAL_MARK:-TESTSETUP}"

PSQL() { docker compose exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 "$@"; }
Q()    { docker compose exec -T postgres psql -U postgres -tAc "$2" -d "$1"; }

# Нормализованные телефоны 8 seed-пользователей (последние 10 цифр) — их НЕ деактивируем.
SEED_PHONES="'9219476577','9995291759','9219032277','9218493337','9500410930','9112300656','9522291717','9313421145'"

echo "==> TEST_ORDER_ID=$TEST_ORDER_ID"
echo "==> TEST_CLIENT_ID=$TEST_CLIENT_ID"

# ── 0. Бэкап ────────────────────────────────────────────────────────────────
TS="$(date +%Y%m%d_%H%M%S)"
BK="backups/$TS"
mkdir -p "$BK"
echo "==> pg_dump → $BK/"
for db in baltoil_auth baltoil_orders baltoil_delivery baltoil_chat; do
  docker compose exec -T postgres pg_dump -U postgres -d "$db" > "$BK/$db.sql"
  echo "    ok: $BK/$db.sql ($(wc -c < "$BK/$db.sql") bytes)"
done

# ── 1. Защита: тестовая заявка существует и у неё есть документы ─────────────
DOCS="$(Q baltoil_orders "SELECT count(*) FROM documents WHERE order_id='$TEST_ORDER_ID'")"
echo "==> Документов у тестовой заявки: $DOCS"
if [ "${DOCS:-0}" -lt 1 ]; then
  echo "!! У тестовой заявки нет документов — ОТМЕНА. Сначала прогоните prod_test_state.py."
  exit 1
fi
CLIENT_OK="$(Q baltoil_auth "SELECT count(*) FROM users WHERE id='$TEST_CLIENT_ID'")"
if [ "${CLIENT_OK:-0}" -lt 1 ]; then
  echo "!! Тестовое юрлицо ($TEST_CLIENT_ID) не найдено в auth — ОТМЕНА."
  exit 1
fi

# ── Подтверждение ───────────────────────────────────────────────────────────
if [ "${FORCE:-0}" != "1" ]; then
  echo
  echo "Будет НЕОБРАТИМО удалено всё, кроме тестовой заявки $TEST_ORDER_ID,"
  echo "и деактивированы все пользователи кроме 8 seed + тест-юрлица."
  read -r -p "Продолжить? введите YES: " ans
  [ "$ans" = "YES" ] || { echo "Отменено."; exit 1; }
fi

# ── 2. orders + contracts ───────────────────────────────────────────────────
echo "==> Чистка заявок (кроме тестовой) и договоров (кроме тест-юрлица)…"
PSQL -d baltoil_orders <<SQL
BEGIN;
DELETE FROM orders    WHERE id <> '$TEST_ORDER_ID';
DELETE FROM contracts WHERE client_id <> '$TEST_CLIENT_ID';
UPDATE orders SET manager_comment='ТЕСТОВАЯ ЗАЯВКА — демонстрация документов, не удалять'
  WHERE id='$TEST_ORDER_ID';
COMMIT;
SQL

# ── 3. fuel_transactions + пересчёт склада ──────────────────────────────────
echo "==> Чистка остатков (оставляем операции тестовой заявки)…"
PSQL -d baltoil_delivery <<SQL
BEGIN;
DELETE FROM fuel_transactions
  WHERE COALESCE(order_id::text,'') <> '$TEST_ORDER_ID'
    AND COALESCE(supplier_name,'')  <> '$ARRIVAL_MARK';
UPDATE fuel_stock fs SET
  current_volume = COALESCE((
    SELECT SUM(CASE WHEN ft.type='arrival' THEN ft.volume ELSE -ft.volume END)
    FROM fuel_transactions ft WHERE ft.fuel_type = fs.fuel_type), 0),
  last_updated = now();
COMMIT;
SQL

# ── 4. Деактивация прочих пользователей ─────────────────────────────────────
echo "==> Деактивация пользователей (кроме 8 seed + тест-юрлица)…"
PSQL -d baltoil_auth <<SQL
BEGIN;
UPDATE users SET is_active=false, is_archived=true, archived_at=now()
  WHERE id <> '$TEST_CLIENT_ID'
    AND right(regexp_replace(coalesce(phone,''),'\D','','g'),10) NOT IN ($SEED_PHONES);
DELETE FROM refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE is_active=false);
COMMIT;
SQL

# ── 5. Сводка ───────────────────────────────────────────────────────────────
echo
echo "================ ИТОГ ================"
echo "Активные пользователи:"
Q baltoil_auth "SELECT role||'  '||full_name||'  '||coalesce(phone,'(нет тел)')||'  '||coalesce(email,'(нет email)') FROM users WHERE is_active=true ORDER BY role,full_name"
echo "Заявки (должна быть 1):"
Q baltoil_orders "SELECT order_number||'  '||status||'  docs='||(SELECT count(*) FROM documents d WHERE d.order_id=o.id) FROM orders o"
echo "Операции остатков:"
Q baltoil_delivery "SELECT type||'  '||fuel_type||'  '||volume||'  '||coalesce(order_number,supplier_name,'') FROM fuel_transactions ORDER BY transaction_date"
echo "Склад:"
Q baltoil_delivery "SELECT fuel_type||'  '||current_volume FROM fuel_stock WHERE current_volume<>0"
echo "====================================="
echo "Бэкап: $BK/  (для отката: psql ... < файл)"
