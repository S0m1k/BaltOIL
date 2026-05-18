#!/usr/bin/env bash
set -uo pipefail
cd /opt/baltoil

echo "=== Login as driver1 ==="
TOKEN=$(curl -sk -m 5 -X POST https://5.42.118.110:8001/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"driver1@baltoil.biz","password":"password123"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

# Use the conversation driver1 created earlier with the manager
CONV_ID=$(curl -sk -m 5 -H "Authorization: Bearer $TOKEN" \
  https://5.42.118.110:8004/conversations \
  | python3 -c 'import json,sys;arr=json.load(sys.stdin);
ids=[c["id"] for c in arr if c["type"]=="internal"];
print(ids[0] if ids else "")')
echo "Conversation: $CONV_ID"

echo
echo "=== Start a call ==="
RESP=$(curl -sk -m 5 -X POST https://5.42.118.110:8006/calls/start \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"conversation_id\":\"$CONV_ID\"}")
echo "$RESP" | python3 -m json.tool 2>&1 | head -8
CALL_ID=$(echo "$RESP" | python3 -c 'import json,sys;print(json.load(sys.stdin)["call_id"])')
echo "call_id: $CALL_ID"

echo
echo "=== Immediately end the call (nobody answered → MISSED) ==="
curl -sk -m 5 -o /dev/null -w 'end -> HTTP %{http_code}\n' \
  -X POST "https://5.42.118.110:8006/calls/$CALL_ID/end" \
  -H "Authorization: Bearer $TOKEN"

sleep 1
echo
echo "=== Last 4 messages in conversation ==="
curl -sk -m 5 -H "Authorization: Bearer $TOKEN" \
  "https://5.42.118.110:8004/conversations/$CONV_ID/messages?limit=4" \
  | python3 -m json.tool 2>&1 | head -80
