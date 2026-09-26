#!/bin/sh
# Runs once, when the Postgres data volume is first created.
# - yogii_migrator owns the schema and runs Alembic migrations.
# - yogii_app is what the API uses: data access only, no DDL, and it can't
#   rewrite or delete audit history (see migration 0003).
# Use URL-safe passwords (for example `openssl rand -hex 24`).
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE yogii_migrator LOGIN PASSWORD '${YOGII_MIGRATOR_PASSWORD}';
CREATE ROLE yogii_app LOGIN PASSWORD '${YOGII_APP_PASSWORD}';
REVOKE ALL ON DATABASE "${POSTGRES_DB}" FROM PUBLIC;
GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO yogii_migrator, yogii_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO yogii_migrator;
GRANT USAGE ON SCHEMA public TO yogii_app;
ALTER DEFAULT PRIVILEGES FOR ROLE yogii_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO yogii_app;
ALTER DEFAULT PRIVILEGES FOR ROLE yogii_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO yogii_app;
SQL
