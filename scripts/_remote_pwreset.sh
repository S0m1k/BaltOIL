#!/usr/bin/env bash
set -euo pipefail
cd /opt/baltoil

# Inline the hash inside the SQL — single-quoted SQL string literal,
# so the '$2b$' prefix can't be interpreted as a positional parameter.
docker compose exec -T postgres \
  psql -U postgres -d baltoil_auth -v ON_ERROR_STOP=1 <<'SQL'
UPDATE users
SET    hashed_password = '$2b$12$ghAHx0BxenS1mSEjuILDfu5IosmvIjMj3ur45vNcorzGqjcnUgG8u'
WHERE  email IN ('manager@baltoil.biz', 'driver1@baltoil.biz', 'driver2@baltoil.biz');

SELECT email, LENGTH(hashed_password) AS len, LEFT(hashed_password, 7) AS prefix
FROM   users
WHERE  email IN ('manager@baltoil.biz', 'driver1@baltoil.biz', 'driver2@baltoil.biz')
ORDER  BY email;
SQL
