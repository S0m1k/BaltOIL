#!/usr/bin/env bash
set -uo pipefail
cd /opt/baltoil

echo "=== Wait for uvicorn --reload to pick up new code ==="
sleep 4
docker logs baltoil-auth_service-1 --tail 10 2>&1

echo
echo "=== Login as driver1 ==="
TOKEN=$(curl -sk -m 5 -X POST https://5.42.118.110:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"driver1@baltoil.biz","password":"password123"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')
echo "got token: ${TOKEN:0:30}…"

echo
echo "=== GET /users/directory as driver ==="
curl -sk -m 5 -H "Authorization: Bearer $TOKEN" \
  https://5.42.118.110:8001/api/v1/users/directory \
  | python3 -m json.tool 2>&1 | head -40

echo
echo "=== GET /users (old endpoint) as driver — should be 403 ==="
curl -sk -m 5 -o /tmp/r.json -w 'HTTP %{http_code}\n' \
  -H "Authorization: Bearer $TOKEN" \
  https://5.42.118.110:8001/api/v1/users
head -c 200 /tmp/r.json; echo
