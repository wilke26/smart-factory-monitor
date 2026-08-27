#!/bin/sh
set -eu

umask 077

backup_id=${BACKUP_ID:-}
backup_root=${BACKUP_DIRECTORY:-/backups}
restore_database=${RESTORE_DATABASE_NAME:-smart_factory_restore}
database_user=${POSTGRES_USER:-smart_factory}

case "$backup_id" in
  "" | *[!A-Za-z0-9._-]* | .* | *..*)
    echo "BACKUP_ID is required and must contain only letters, digits, dots, underscores, or hyphens" >&2
    exit 2
    ;;
esac
if [ "${#backup_id}" -gt 64 ]; then
  echo "BACKUP_ID must not exceed 64 characters" >&2
  exit 2
fi

case "$restore_database" in
  "" | *[!A-Za-z0-9_]*)
    echo "RESTORE_DATABASE_NAME must be a simple PostgreSQL identifier" >&2
    exit 2
    ;;
esac

if [ "$restore_database" = "${POSTGRES_DB:-smart_factory}" ]; then
  echo "RESTORE_DATABASE_NAME must differ from the active database" >&2
  exit 2
fi

backup_directory="$backup_root/$backup_id"
for required_file in BACKUP-METADATA SHA256SUMS database.dump model-registry.tar.gz model-signing-public.pem; do
  if [ ! -f "$backup_directory/$required_file" ]; then
    echo "backup is incomplete: missing $required_file" >&2
    exit 1
  fi
done

if [ "$(wc -l < "$backup_directory/SHA256SUMS" | tr -d ' ')" != "4" ] \
  || awk '$2 != "BACKUP-METADATA" && $2 != "database.dump" && $2 != "model-registry.tar.gz" && $2 != "model-signing-public.pem" { unexpected=1 } END { exit unexpected ? 0 : 1 }' \
    "$backup_directory/SHA256SUMS"; then
  echo "backup checksum manifest contains unexpected entries" >&2
  exit 1
fi

(
  cd "$backup_directory"
  sha256sum -c SHA256SUMS
)

if ! grep -Fqx 'format_version=1' "$backup_directory/BACKUP-METADATA"; then
  echo "unsupported backup format" >&2
  exit 1
fi
if ! grep -Fqx "backup_id=$backup_id" "$backup_directory/BACKUP-METADATA"; then
  echo "backup metadata does not match BACKUP_ID" >&2
  exit 1
fi

if tar --list --gzip --file="$backup_directory/model-registry.tar.gz" \
  | awk '/^\// || /(^|\/)\.\.($|\/)/ { found=1 } END { exit found ? 0 : 1 }'; then
  echo "model registry archive contains an unsafe path" >&2
  exit 1
fi
if tar --list --verbose --gzip --file="$backup_directory/model-registry.tar.gz" \
  | awk 'substr($1, 1, 1) != "-" && substr($1, 1, 1) != "d" { found=1 } END { exit found ? 0 : 1 }'; then
  echo "model registry archive contains a link or special file" >&2
  exit 1
fi

dropdb --host=timescaledb --username="$database_user" --if-exists --force "$restore_database"
createdb --host=timescaledb --username="$database_user" "$restore_database"
pg_restore \
  --host=timescaledb \
  --username="$database_user" \
  --dbname="$restore_database" \
  --exit-on-error \
  --no-owner \
  --no-acl \
  "$backup_directory/database.dump"

find /restored-models -mindepth 1 -delete
find /restored-model-signing-public -mindepth 1 -delete
tar --extract --gzip --file="$backup_directory/model-registry.tar.gz" \
  --directory=/restored-models
cp "$backup_directory/model-signing-public.pem" \
  /restored-model-signing-public/public.pem
chmod 0444 /restored-model-signing-public/public.pem

echo "{\"event\":\"backup_restored\",\"backup_id\":\"$backup_id\",\"database_name\":\"$restore_database\"}"
