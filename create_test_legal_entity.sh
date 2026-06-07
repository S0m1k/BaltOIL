#!/usr/bin/env bash
#
# Создание ТЕСТОВОГО клиента-юрлица на проде через DaData (автозаполнение по ИНН).
# Запускать НА ПРОД-СЕРВЕРЕ из /opt/baltoil:
#     ssh root@5.42.118.110
#     cd /opt/baltoil
#     bash create_test_legal_entity.sh
#
# Реквизиты (company_name/КПП/ОГРН/юр.адрес/банк/директор) подтянутся из ЕГРЮЛ
# автоматически — на проде настроен DADATA_API_KEY. Руками задаём только контакт,
# ИНН и (опционально) БИК + расчётный счёт.
#
set -euo pipefail

# ─── ПАРАМЕТРЫ (поменяйте при необходимости) ───────────────────────────────────
INN="${INN:-7707083893}"                 # ← реальный ИНН тестовой компании (10 или 12 цифр)
EMAIL="${EMAIL:-testbiz@baltoil.ru}"
PHONE="${PHONE:-+7 999 200 30 40}"
PASSWORD="${PASSWORD:-Test1234}"
FULL_NAME="${FULL_NAME:-Контактное Лицо Тестовое}"
BIK="${BIK:-}"                            # ← опц.: БИК банка (для автозагрузки реквизитов банка из DaData)
BANK_ACCOUNT="${BANK_ACCOUNT:-}"          # ← опц.: расчётный счёт (DaData его не знает, вводится вручную)
DELIVERY_ADDRESS="${DELIVERY_ADDRESS:-}"  # ← опц.: адрес доставки

BASE="${BASE:-https://localhost}"         # на сервере nginx слушает 443; -k из-за самоподписанного/доменного серта
REG_URL="$BASE/api/auth/api/v1/auth/register/company"
# ───────────────────────────────────────────────────────────────────────────────

echo "==> Регистрация юрлица по ИНН $INN (email=$EMAIL)"

# Собираем JSON-тело (опциональные поля добавляем только если заданы)
body=$(python3 - "$EMAIL" "$PHONE" "$PASSWORD" "$FULL_NAME" "$INN" "$BIK" "$BANK_ACCOUNT" "$DELIVERY_ADDRESS" <<'PY'
import json, sys
email, phone, password, full_name, inn, bik, acc, deliv = sys.argv[1:9]
d = {"email": email, "phone": phone, "password": password, "full_name": full_name, "inn": inn}
if bik:   d["bik"] = bik
if acc:   d["bank_account"] = acc
if deliv: d["delivery_address"] = deliv
print(json.dumps(d, ensure_ascii=False))
PY
)

# POST /register/company  → 201 (+автологин-токены) | 409 если email/телефон заняты
resp=$(curl -sk -w $'\n%{http_code}' -X POST "$REG_URL" \
  -H "Content-Type: application/json" \
  --data "$body")
code=$(printf '%s' "$resp" | tail -n1)
payload=$(printf '%s' "$resp" | sed '$d')

case "$code" in
  201) echo "    ✓ зарегистрировано (201). Логин: $EMAIL / $PASSWORD" ;;
  409) echo "    ! уже существует (409) — email или телефон заняты. Профиль ниже (если есть)." ;;
  422) echo "    ✗ 422 ошибка валидации:"; echo "$payload"; exit 1 ;;
  *)   echo "    ✗ неожиданный код $code:"; echo "$payload"; exit 1 ;;
esac

echo
echo "==> Реквизиты в БД (что подтянулось из DaData):"
docker compose exec -T postgres psql -U postgres -d baltoil_auth -P pager=off -c "
SELECT u.email, p.company_name, p.inn, p.kpp, p.ogrn, p.legal_address,
       p.bank_name, p.bik, p.bank_account, p.director_name,
       p.fns_last_sync_at
FROM users u JOIN client_profiles p ON p.user_id = u.id
WHERE u.email = '${EMAIL//\'/\'\'}';"

echo
echo "Готово. Если ОГРН/директор пустые — значит DaData по этому ИНН ничего не вернула"
echo "(нет в ЕГРЮЛ / лимит ключа). Тогда можно дернуть ресинк:"
echo "  POST /api/auth/api/v1/users/{user_id}/fns-resync  (admin/manager)"
