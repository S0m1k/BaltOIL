#!/usr/bin/env bash
set -euo pipefail

NEW='https://5.42.118.110,http://5.42.118.110:8080,http://5.42.118.110'
F=/opt/baltoil/delivery_service/.env

echo "Before:"
grep '^ALLOWED_ORIGINS=' "$F" || echo "(missing)"

if grep -q '^ALLOWED_ORIGINS=' "$F"; then
  sed -i "s|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=${NEW}|" "$F"
else
  echo "ALLOWED_ORIGINS=${NEW}" >> "$F"
fi

echo "After:"
grep '^ALLOWED_ORIGINS=' "$F"

echo
echo "Restarting delivery_service..."
cd /opt/baltoil
docker compose restart delivery_service

sleep 4
echo
echo "--- new logs ---"
docker logs baltoil-delivery_service-1 --tail 15 2>&1
