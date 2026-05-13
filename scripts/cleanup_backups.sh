#!/bin/bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/var/backups/baltoil}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

find "$BACKUP_DIR" -name "*.sql.gz" -mtime +"$RETENTION_DAYS" -delete
echo "[$(date -Iseconds)] Cleaned backups older than ${RETENTION_DAYS} days in $BACKUP_DIR"
