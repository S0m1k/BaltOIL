#!/usr/bin/env bash
set -euo pipefail

cd /opt/baltoil

echo "========================================"
echo "[4/6] Patch livekit/config.yaml use_external_ip: true"
echo "========================================"
sed -i 's/^\(\s*\)use_external_ip:\s*false/\1use_external_ip: true/' /opt/baltoil/livekit/config.yaml
grep -n 'use_external_ip' /opt/baltoil/livekit/config.yaml || true

echo
echo "========================================"
echo "[5/6] Build & start call_service + livekit"
echo "========================================"
docker compose up -d --build livekit call_service 2>&1

echo
echo "========================================"
echo "[6/6] Restart notification_service (enum migration in lifespan)"
echo "========================================"
docker compose restart notification_service

echo
echo "========================================"
echo "Done. docker compose ps:"
echo "========================================"
docker compose ps
