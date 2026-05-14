#!/bin/bash
# Cloud sync: uploads /var/backups/baltoil/ to S3-compatible storage.
# Activated by setting BACKUP_CLOUD_PROVIDER in scripts/backup.env.
# If BACKUP_CLOUD_PROVIDER is empty or unset — exits silently with code 0.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/backup.env"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  . "$ENV_FILE"
fi

if [ -z "${BACKUP_CLOUD_PROVIDER:-}" ]; then
  echo "[$(date -Iseconds)] Cloud sync skipped: BACKUP_CLOUD_PROVIDER not set in $ENV_FILE"
  exit 0
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/baltoil}"

case "$BACKUP_CLOUD_PROVIDER" in
  s3|yandex|selectel)
    # Uses AWS CLI with custom endpoint — works for any S3-compatible storage.
    # For Yandex Object Storage: BACKUP_CLOUD_ENDPOINT=https://storage.yandexcloud.net
    AWS_ACCESS_KEY_ID="$BACKUP_CLOUD_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$BACKUP_CLOUD_SECRET_KEY" \
    aws s3 sync "$BACKUP_DIR/" "s3://${BACKUP_CLOUD_BUCKET}/baltoil/" \
      --endpoint-url "$BACKUP_CLOUD_ENDPOINT" \
      --exclude "*" --include "*.sql.gz" \
      --no-progress
    echo "[$(date -Iseconds)] Cloud sync OK -> $BACKUP_CLOUD_PROVIDER / $BACKUP_CLOUD_BUCKET"
    ;;
  *)
    echo "[ERROR] Unknown BACKUP_CLOUD_PROVIDER: $BACKUP_CLOUD_PROVIDER"
    echo "[ERROR] Supported values: s3, yandex, selectel"
    exit 1
    ;;
esac
