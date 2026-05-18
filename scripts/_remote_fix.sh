#!/usr/bin/env bash
set -euo pipefail
cd /opt/baltoil

echo "===== Patch alembic 0001 to skip duplicate enum create ====="
# The column-implicit enum tried to CREATE TYPE without IF NOT EXISTS.
# Tell it to skip — the explicit .create(checkfirst=True) above handles it.
sed -i 's/sa\.Enum("ringing", "active", "ended", "missed", name="callstatus"),/sa.Enum("ringing", "active", "ended", "missed", name="callstatus", create_type=False),/' \
    /opt/baltoil/call_service/alembic/versions/0001_baseline.py
grep -n 'create_type=False' /opt/baltoil/call_service/alembic/versions/0001_baseline.py || { echo "PATCH FAILED"; exit 1; }

echo
echo "===== Clean up partial DB state (drop type left by failed migration) ====="
docker compose exec -T postgres psql -U postgres -d baltoil_calls -c "DROP TYPE IF EXISTS callstatus CASCADE;" || true
docker compose exec -T postgres psql -U postgres -d baltoil_calls -c "DELETE FROM alembic_version;" 2>/dev/null || true
docker compose exec -T postgres psql -U postgres -d baltoil_calls -c "\dt"

echo
echo "===== Recreate call_service container ====="
docker compose up -d call_service
sleep 5
docker compose ps call_service
echo
docker logs baltoil-call_service-1 --tail 25 2>&1

echo
echo "===== Health check ====="
sleep 3
curl -sS -m 5 http://localhost:8006/health || echo "health: FAIL"
echo
echo
echo "===== DB tables ====="
docker compose exec -T postgres psql -U postgres -d baltoil_calls -c "\dt"
docker compose exec -T postgres psql -U postgres -d baltoil_calls -c "\dT"
