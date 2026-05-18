#!/usr/bin/env bash
set -euo pipefail
cd /opt/baltoil

NEW_ORIGINS='https://5.42.118.110,http://5.42.118.110:8080,http://5.42.118.110'

echo "===== [1/4] Update ALLOWED_ORIGINS in each service's .env ====="
for svc in auth_service order_service chat_service notification_service call_service; do
    f="/opt/baltoil/${svc}/.env"
    if [ -f "$f" ]; then
        if grep -q '^ALLOWED_ORIGINS=' "$f"; then
            sed -i "s|^ALLOWED_ORIGINS=.*|ALLOWED_ORIGINS=${NEW_ORIGINS}|" "$f"
        else
            echo "ALLOWED_ORIGINS=${NEW_ORIGINS}" >> "$f"
        fi
        echo "  ${svc}: $(grep '^ALLOWED_ORIGINS=' "$f")"
    fi
done

echo
echo "===== [2/4] Update call_service LIVEKIT_PUBLIC_URL → wss:// ====="
sed -i 's|^LIVEKIT_PUBLIC_URL=.*|LIVEKIT_PUBLIC_URL=wss://5.42.118.110:7880|' /opt/baltoil/call_service/.env
grep '^LIVEKIT_PUBLIC_URL=' /opt/baltoil/call_service/.env

echo
echo "===== [3/4] Sanity-check uploaded files ====="
docker compose config --quiet && echo "compose: OK"
docker run --rm -v /opt/baltoil/frontend/nginx.conf:/etc/nginx/conf.d/default.conf:ro -v /opt/baltoil/tls:/etc/nginx/tls:ro nginx:alpine nginx -t 2>&1 || { echo "nginx config FAILED"; exit 1; }

echo
echo "===== [4/4] Recreate stack (removes old containers with stale port mappings) ====="
docker compose up -d --remove-orphans

echo
echo "===== docker compose ps ====="
docker compose ps
