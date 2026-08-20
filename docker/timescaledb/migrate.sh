#!/bin/sh
set -eu

psql_db() {
  psql -h timescaledb -U "${POSTGRES_USER:-smart_factory}" \
    -d "${POSTGRES_DB:-smart_factory}" "$@"
}

psql_db -v ON_ERROR_STOP=1 -c \
  "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())"

for migration in /migrations/*.sql; do
  version=${migration##*/}
  applied=$(psql_db -At -v ON_ERROR_STOP=1 -c \
    "SELECT 1 FROM schema_migrations WHERE version = '$version'")
  if [ "$applied" = "1" ]; then
    echo "migration already applied: $version"
    continue
  fi
  echo "applying migration: $version"
  psql_db -v ON_ERROR_STOP=1 -1 -f "$migration" -c \
    "INSERT INTO schema_migrations (version) VALUES ('$version')"
done
