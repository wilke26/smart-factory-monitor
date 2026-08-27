#!/bin/sh
set -eu

umask 077

backup_id=${BACKUP_ID:-$(date -u +%Y%m%dT%H%M%SZ)}
backup_root=${BACKUP_DIRECTORY:-/backups}
database_name=${POSTGRES_DB:-smart_factory}
database_user=${POSTGRES_USER:-smart_factory}

case "$backup_id" in
  "" | *[!A-Za-z0-9._-]* | .* | *..*)
    echo "BACKUP_ID must contain only letters, digits, dots, underscores, or hyphens and must not start with a dot" >&2
    exit 2
    ;;
esac
if [ "${#backup_id}" -gt 64 ]; then
  echo "BACKUP_ID must not exceed 64 characters" >&2
  exit 2
fi

case "$database_name" in
  "" | *[!A-Za-z0-9_]*)
    echo "POSTGRES_DB must be a simple PostgreSQL identifier" >&2
    exit 2
    ;;
esac

if [ ! -r /model-signing-public/public.pem ]; then
  echo "model verification public key is missing" >&2
  exit 1
fi

mkdir -p "$backup_root"
final_directory="$backup_root/$backup_id"
partial_directory="$backup_root/.${backup_id}.partial"

if [ -e "$final_directory" ] || [ -e "$partial_directory" ]; then
  echo "backup destination already exists: $backup_id" >&2
  exit 1
fi

mkdir "$partial_directory"
cleanup() {
  if [ -d "$partial_directory" ]; then
    find "$partial_directory" -mindepth 1 -delete
    rmdir "$partial_directory"
  fi
}
trap cleanup EXIT HUP INT TERM

pg_dump \
  --host=timescaledb \
  --username="$database_user" \
  --dbname="$database_name" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-acl \
  --file="$partial_directory/database.dump"

tar --create --gzip --file="$partial_directory/model-registry.tar.gz" \
  --directory=/models .
cp /model-signing-public/public.pem "$partial_directory/model-signing-public.pem"

cat > "$partial_directory/BACKUP-METADATA" <<EOF
format_version=1
backup_id=$backup_id
created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
database_name=$database_name
EOF

(
  cd "$partial_directory"
  sha256sum BACKUP-METADATA database.dump model-registry.tar.gz model-signing-public.pem \
    > SHA256SUMS
)

mv "$partial_directory" "$final_directory"
trap - EXIT HUP INT TERM
echo "{\"event\":\"backup_created\",\"backup_id\":\"$backup_id\"}"
