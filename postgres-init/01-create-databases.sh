#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE baltoil_orders;
    CREATE DATABASE baltoil_delivery;
    CREATE DATABASE baltoil_chat;
    CREATE DATABASE baltoil_notifications;
EOSQL
