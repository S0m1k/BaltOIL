#!/bin/bash
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "Usage: $0 <db_name> <backup_file.sql.gz>"
  echo "Example: $0 baltoil_orders /var/backups/baltoil/baltoil_orders_20260513_040000.sql.gz"
  exit 1
fi

DB="$1"
FILE="$2"

if [ ! -f "$FILE" ]; then
  echo "[ERROR] Backup file not found: $FILE"
  exit 1
fi

echo ""
echo "========================================="
echo "  DATABASE RESTORE"
echo "========================================="
echo "  Database : $DB"
echo "  Backup   : $FILE"
echo "  Size     : $(du -sh "$FILE" | cut -f1)"
echo "========================================="
echo ""
echo "[!] This will DROP and recreate '$DB'."
echo "[!] All current data will be LOST."
echo ""
printf "Type 'yes' to continue: "
read -r CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "Aborted."; exit 1; }

echo "[$(date -Iseconds)] Dropping database $DB..."
docker exec baltoil-postgres-1 psql -U postgres -c "DROP DATABASE IF EXISTS ${DB};"

echo "[$(date -Iseconds)] Creating database $DB..."
docker exec baltoil-postgres-1 psql -U postgres -c "CREATE DATABASE ${DB};"

echo "[$(date -Iseconds)] Restoring from $FILE..."
gunzip -c "$FILE" | docker exec -i baltoil-postgres-1 psql -U postgres "$DB"

echo "[$(date -Iseconds)] Restore complete: $DB"
