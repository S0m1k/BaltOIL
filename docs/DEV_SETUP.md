# BaltOIL — Dev Setup

## Prerequisites

- Docker + Docker Compose
- `make` (on Windows: use WSL or Git Bash)

## Starting from scratch

```bash
# 1. Clone and enter repo
git clone <repo> && cd baltoil

# 2. Copy .env files (first time only — get from team)
cp auth_service/.env.example auth_service/.env
cp order_service/.env.example order_service/.env
cp delivery_service/.env.example delivery_service/.env
cp chat_service/.env.example chat_service/.env
cp notification_service/.env.example notification_service/.env

# 3. Start all services (migrations run automatically on startup)
docker compose up -d

# 4. Seed test data
make seed
```

## Test user logins

All passwords: `password123`

| Email | Role |
|-------|------|
| `admin@baltoil.test` | admin |
| `manager1@baltoil.test` | manager |
| `manager2@baltoil.test` | manager |
| `driver1@baltoil.test` | driver |
| `driver2@baltoil.test` | driver |
| `prepaid@baltoil.test` | client (prepaid) |
| `ondelivery@baltoil.test` | client (on delivery) |
| `tradecredit@baltoil.test` | client (trade credit) |
| `postpaid@baltoil.test` | client (postpaid) |
| `company@baltoil.test` | client (company) |

Frontend: http://localhost:8080

## Resetting data

```bash
# Wipe everything and reseed (destroys all data)
make seed-fresh

# Or just reseed without wiping (overwrites known seed records, keeps other data)
make seed
```

## Running Alembic migrations manually

```bash
# Check current revision
docker compose exec auth_service alembic current

# Apply all pending migrations
docker compose exec auth_service alembic upgrade head

# Roll back one migration
docker compose exec auth_service alembic downgrade -1
```

(Replace `auth_service` with `order_service`, `delivery_service`, or `chat_service` as needed.)

## Logs

```bash
# All services
docker compose logs -f

# Single service
docker compose logs -f order_service
```
