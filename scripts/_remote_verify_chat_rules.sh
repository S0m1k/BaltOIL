#!/usr/bin/env bash
set -uo pipefail

echo "=== Login as driver1 ==="
TOKEN=$(curl -sk -m 5 -X POST https://5.42.118.110:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"driver1@baltoil.biz","password":"password123"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

echo "=== driver: try to create CLIENT_SUPPORT chat (must be 403) ==="
curl -sk -m 5 -o /tmp/r.json -w 'HTTP %{http_code}\n' \
  -X POST https://5.42.118.110:8004/conversations \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"type":"client_support","participant_ids":[]}'
head -c 200 /tmp/r.json; echo

echo
echo "=== driver: try to create INTERNAL chat WITH a client (must be 403) ==="
# Get a client user id
CLIENT_ID=$(curl -sk -m 5 -H "Authorization: Bearer $TOKEN" \
  'https://5.42.118.110:8001/api/v1/users/directory?role=client&limit=1' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)[0]["id"])')
echo "Using client id: $CLIENT_ID"
curl -sk -m 5 -o /tmp/r.json -w 'HTTP %{http_code}\n' \
  -X POST https://5.42.118.110:8004/conversations \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"type\":\"internal\",\"participant_ids\":[\"$CLIENT_ID\"]}"
head -c 200 /tmp/r.json; echo

echo
echo "=== driver: legit — INTERNAL chat with another driver (must be 200/201) ==="
DRIVER2_ID=$(curl -sk -m 5 -H "Authorization: Bearer $TOKEN" \
  'https://5.42.118.110:8001/api/v1/users/directory?role=driver&limit=5' \
  | python3 -c 'import json,sys;[print(u["id"]) for u in json.load(sys.stdin) if u["full_name"]!="Иван Сидоров"][0:1]')
echo "Inviting driver: $DRIVER2_ID"
if [ -n "$DRIVER2_ID" ]; then
  curl -sk -m 5 -o /tmp/r.json -w 'HTTP %{http_code}\n' \
    -X POST https://5.42.118.110:8004/conversations \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"type\":\"internal\",\"title\":\"Test from script\",\"participant_ids\":[\"$DRIVER2_ID\"]}"
  head -c 250 /tmp/r.json; echo
fi
