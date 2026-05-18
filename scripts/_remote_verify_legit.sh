#!/usr/bin/env bash
set -uo pipefail
TOKEN=$(curl -sk -m 5 -X POST https://5.42.118.110:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"driver1@baltoil.biz","password":"password123"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

MANAGER_ID=$(curl -sk -m 5 -H "Authorization: Bearer $TOKEN" \
  'https://5.42.118.110:8001/api/v1/users/directory?role=manager&limit=1' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')

echo "Inviting manager: $MANAGER_ID"
curl -sk -m 5 -o /tmp/r.json -w 'HTTP %{http_code}\n' \
  -X POST https://5.42.118.110:8004/conversations \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"type\":\"internal\",\"title\":\"Driver-Manager test\",\"participant_ids\":[\"$MANAGER_ID\"]}"
head -c 250 /tmp/r.json; echo
