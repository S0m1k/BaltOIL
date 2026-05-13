#!/bin/sh
set -e
echo "Running Alembic migrations for delivery_service..."
alembic upgrade head
echo "Migrations done. Starting server..."
exec "$@"
