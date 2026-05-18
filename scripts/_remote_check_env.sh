#!/usr/bin/env bash
for svc in auth_service order_service delivery_service chat_service notification_service call_service; do
    echo "--- ${svc} ---"
    grep '^ALLOWED_ORIGINS=' "/opt/baltoil/${svc}/.env" 2>/dev/null || echo "(no .env or no ALLOWED_ORIGINS)"
done

echo
echo "--- recent delivery_service logs ---"
docker logs baltoil-delivery_service-1 --tail 30 2>&1
