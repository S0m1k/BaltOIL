#!/usr/bin/env bash
cd /opt/baltoil
docker compose exec -T postgres psql -U postgres -d baltoil_auth <<'SQL'
SELECT email, phone, role,
       LEFT(hashed_password, 7) AS hash_prefix,
       LENGTH(hashed_password)  AS hash_len,
       CASE WHEN hashed_password ~ '^\$2[abxy]\$' THEN 'OK' ELSE 'BROKEN' END AS bcrypt_valid
FROM users
ORDER BY bcrypt_valid DESC, role, email;
SQL
