#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/baltoil}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DATABASES=("baltoil_auth" "baltoil_orders" "baltoil_delivery" "baltoil_chat")

mkdir -p "$BACKUP_DIR"

for DB in "${DATABASES[@]}"; do
  FILE="$BACKUP_DIR/${DB}_${TIMESTAMP}.sql.gz"
  docker exec baltoil-postgres-1 pg_dump -U postgres "$DB" | gzip > "$FILE"
  echo "[$(date -Iseconds)] Backed up $DB -> $FILE"
done

# Cloud sync (no-op if BACKUP_CLOUD_PROVIDER not configured)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -x "$SCRIPT_DIR/sync_backups_to_cloud.sh" ]; then
  "$SCRIPT_DIR/sync_backups_to_cloud.sh" || echo "[WARN] cloud sync failed (non-fatal)"
fi
