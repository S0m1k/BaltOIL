# BaltOIL Database Backup & Restore

## Where backups live

Local backups: `/var/backups/baltoil/`
Format: `{db_name}_{YYYYMMDD_HHMMSS}.sql.gz`
Retention: 14 days (configurable via `RETENTION_DAYS` env var)

## Setting up automated backups on the prod server

```bash
# 1. Make scripts executable (once)
chmod +x /opt/baltoil/scripts/*.sh

# 2. Install cron jobs
crontab -e
# Paste contents of /opt/baltoil/crontab.example

# 3. Verify cron is installed
crontab -l

# 4. Test manually
/opt/baltoil/scripts/backup_db.sh
ls /var/backups/baltoil/
```

## Enabling cloud sync (optional)

Cloud sync is disabled by default. To enable:

```bash
# Copy template
cp /opt/baltoil/scripts/backup.env.example /opt/baltoil/scripts/backup.env

# Fill in credentials (keep this file secret — never commit it)
chmod 600 /opt/baltoil/scripts/backup.env
nano /opt/baltoil/scripts/backup.env
```

Cloud sync fires automatically after each local backup run. Requires `aws-cli` installed:
```bash
apt-get install -y awscli   # or: pip install awscli
```

## Restoring a database

```bash
# List available backups
ls -lh /var/backups/baltoil/

# Restore a specific backup
/opt/baltoil/scripts/restore_db.sh baltoil_orders /var/backups/baltoil/baltoil_orders_20260513_040000.sql.gz
```

The script will ask for confirmation before dropping and recreating the database.

**After restore:** run `alembic upgrade head` inside each affected service container if needed
(usually not needed — backup contains schema + data).

## Restore drill log

Perform a restore drill at least once after setup, then after every major schema change.

| Date | Time to restore | Tester | Notes |
|------|----------------|--------|-------|
| 2026-05-13 | 8s | Sonnet (automated) | Temp postgres container on prod server. All 4 DBs restored OK: 6 users, 2 orders, 1 vehicle, 3 conversations. |

To record a drill:
1. On a clean machine (or temp Docker container), run `docker compose up -d`
2. Copy a production backup
3. Run `./scripts/restore_db.sh` for each DB
4. Verify login and basic functionality
5. Record time + result in the table above
