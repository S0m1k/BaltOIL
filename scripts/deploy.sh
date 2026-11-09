#!/usr/bin/env bash
# Серверный деплой BaltOIL. Запускается на проде из CI (.github/workflows/deploy.yml)
# или руками:  ssh root@5.42.118.110 /opt/baltoil/scripts/deploy.sh
#
# Что делает:
#   1. git fast-forward до origin/master (расхождение истории -> стоп, ничего не ломаем);
#   2. по списку изменённых файлов решает, что трогать:
#        - requirements.txt / Dockerfile сервиса  -> пересборка образа (up -d --build)
#        - только код сервиса (bind-mount)        -> restart
#        - docker-compose.yml                     -> up -d
#        - frontend/nginx.conf                    -> nginx -s reload
#        - frontend/*.html                        -> ничего (bind-mount, отдаётся сразу)
#   3. alembic upgrade head для затронутых сервисов (миграции идемпотентны, см. DEPLOY.md);
#   4. проверяет, что все контейнеры running и фронт отвечает.
# Откат: см. вывод при ошибке (git reset --hard <старый коммит> + этот же скрипт).
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/baltoil}"
BRANCH="${BRANCH:-master}"
BACKEND_SERVICES=(auth_service order_service delivery_service chat_service call_service notification_service)
MIGRATED_SERVICES=(auth_service order_service delivery_service chat_service)

cd "$APP_DIR"
exec 9>/tmp/baltoil-deploy.lock
flock -n 9 || { echo "Деплой уже идёт (lock)"; exit 1; }

OLD="$(git rev-parse HEAD)"
git fetch --prune origin "$BRANCH"
git merge --ff-only "origin/$BRANCH"
NEW="$(git rev-parse HEAD)"

if [ "$OLD" = "$NEW" ]; then
  echo "Нового кода нет ($NEW) — проверяю только здоровье."
  CHANGED=""
else
  echo "Деплой $OLD -> $NEW"
  git log --oneline "$OLD..$NEW"
  CHANGED="$(git diff --name-only "$OLD" "$NEW")"
fi

changed() { grep -qE "$1" <<<"$CHANGED"; }

if changed '^docker-compose\.yml$'; then
  echo "==> docker-compose.yml изменился: up -d"
  docker compose up -d
fi

for svc in "${BACKEND_SERVICES[@]}"; do
  changed "^${svc}/" || continue
  if changed "^${svc}/(requirements.*\.txt|Dockerfile)"; then
    echo "==> $svc: зависимости/образ изменились — пересборка"
    docker compose up -d --build --no-deps "$svc"
  else
    echo "==> $svc: код изменился — restart (bind-mount)"
    docker compose restart "$svc"
  fi
done

# Дать сервисам подняться перед миграциями
sleep 8
for svc in "${MIGRATED_SERVICES[@]}"; do
  changed "^${svc}/" || continue
  echo "==> alembic upgrade head: $svc"
  docker compose exec -T "$svc" alembic upgrade head
done

if changed '^frontend/nginx\.conf$'; then
  echo "==> nginx.conf изменился: проверка и reload"
  docker compose exec -T frontend nginx -t
  docker compose exec -T frontend nginx -s reload
fi

echo "==> Проверка здоровья"
FAILED=0
while read -r name state; do
  if [ "$state" != "running" ]; then
    echo "  ✗ $name: $state"; FAILED=1
  fi
done < <(docker compose ps --format '{{.Service}} {{.State}}')

# На этом хосте фронт стоит за внешним прокси и на 443 самого хоста не слушает
# (https://localhost/ даёт 000), поэтому проверяем публичный адрес. Переопределяется
# переменной HEALTH_URL.
HEALTH_URL="${HEALTH_URL:-https://crm.9171517.ru/}"
if ! curl -ksf -o /dev/null --max-time 15 "$HEALTH_URL"; then
  echo "  ✗ фронт ($HEALTH_URL) не отвечает"; FAILED=1
fi

if [ "$FAILED" -ne 0 ]; then
  echo "ДЕПЛОЙ НЕУСПЕШЕН. Откат:  cd $APP_DIR && git reset --hard $OLD && scripts/deploy.sh"
  exit 1
fi
echo "OK: $NEW"
