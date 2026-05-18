#!/usr/bin/env bash
set -euo pipefail
cd /opt/baltoil

F=/opt/baltoil/chat_service/.env
SECRET='baltoil-internal-secret-2026'
AUTH_URL='http://auth_service:8001/api/v1'

# Ensure INTERNAL_API_SECRET is present
if grep -q '^INTERNAL_API_SECRET=' "$F"; then
  sed -i "s|^INTERNAL_API_SECRET=.*|INTERNAL_API_SECRET=${SECRET}|" "$F"
else
  echo "INTERNAL_API_SECRET=${SECRET}" >> "$F"
fi

# Ensure AUTH_SERVICE_URL is present
if grep -q '^AUTH_SERVICE_URL=' "$F"; then
  sed -i "s|^AUTH_SERVICE_URL=.*|AUTH_SERVICE_URL=${AUTH_URL}|" "$F"
else
  echo "AUTH_SERVICE_URL=${AUTH_URL}" >> "$F"
fi

echo "--- chat_service/.env (relevant) ---"
grep -E '^(INTERNAL_API_SECRET|AUTH_SERVICE_URL|ALLOWED_ORIGINS)=' "$F"

echo
echo "--- Recreate chat_service to pick up new env_file ---"
docker compose up -d --force-recreate chat_service
sleep 4
echo
echo "--- chat_service logs ---"
docker logs baltoil-chat_service-1 --tail 12 2>&1
