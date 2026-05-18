#!/usr/bin/env bash
for u in manager@baltoil.biz driver1@baltoil.biz driver2@baltoil.biz admin@baltoil.biz; do
  echo "--- $u ---"
  curl -sk -m 5 -o /tmp/r.json -w 'HTTP %{http_code}\n' \
    -X POST https://5.42.118.110:8001/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$u\",\"password\":\"password123\"}"
  head -c 180 /tmp/r.json; echo
done
echo
echo "--- recent auth logs ---"
docker logs baltoil-auth_service-1 --tail 10 2>&1
