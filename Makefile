.PHONY: seed seed-fresh

# Populate all service DBs with test data.
# Runs in each service's container — services must be up.
# FORBIDDEN on APP_ENV=production (enforced in each script).
seed:
	@echo "==> Seeding auth_service (users, profiles)..."
	docker compose exec auth_service python /app/scripts/seed.py
	@echo "==> Seeding order_service (orders, payments)..."
	docker compose exec order_service python /app/scripts/seed.py
	@echo "==> Seeding chat_service (conversations, messages)..."
	docker compose exec chat_service python /app/scripts/seed.py
	@echo "==> Seed complete. Login: admin@baltoil.test / password123"

# Wipe volumes, restart from scratch, then seed.
seed-fresh:
	@echo "==> Wiping volumes and restarting..."
	docker compose down -v
	docker compose up -d
	@echo "==> Waiting for services to be ready..."
	sleep 8
	$(MAKE) seed
