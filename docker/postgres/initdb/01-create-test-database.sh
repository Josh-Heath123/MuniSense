#!/usr/bin/env bash
# Runs once, when the volume is first initialised: creates the separate test database
# next to the development database (POSTGRES_DB), owned by the same local user.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v test_db="$MUNISENSE_TEST_DB_NAME" -v owner="$POSTGRES_USER" <<'SQL'
CREATE DATABASE :"test_db" OWNER :"owner";
SQL
