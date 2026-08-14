#!/usr/bin/env bash

set -euo pipefail
umask 077

database_name="${1:-dnd_planner}"
container_name="${POSTGRES_CONTAINER:-postgres-postgres-1}"
backup_directory="${BACKUP_DIRECTORY:-/opt/apps/dnd-planner/backups}"

if [[ ! "$database_name" =~ ^[a-z][a-z0-9_]{0,62}$ ]]; then
    printf 'Unsafe PostgreSQL database name: %s\n' "$database_name" >&2
    exit 2
fi

if [[ ! -d "$backup_directory" ]]; then
    printf 'Backup directory does not exist: %s\n' "$backup_directory" >&2
    exit 2
fi

timestamp="$(date -u +%Y%m%dT%H%M%S%NZ)"
base_name="${database_name}-${timestamp}"
dump_path="${backup_directory}/${base_name}.dump"
checksum_path="${dump_path}.sha256"
metadata_path="${dump_path}.metadata"
temporary_dump="${dump_path}.tmp"
temporary_metadata="${metadata_path}.tmp"
temporary_checksum="${checksum_path}.tmp"
published=false

for output_path in \
    "$dump_path" \
    "$checksum_path" \
    "$metadata_path" \
    "$temporary_dump" \
    "$temporary_metadata" \
    "$temporary_checksum"; do
    if [[ -e "$output_path" ]]; then
        printf 'Refusing to overwrite backup artifact: %s\n' "$output_path" >&2
        exit 3
    fi
done

cleanup() {
    rm -f -- "$temporary_dump" "$temporary_metadata" "$temporary_checksum"
    if [[ "$published" != true ]]; then
        rm -f -- "$dump_path" "$metadata_path" "$checksum_path"
    fi
}
trap cleanup EXIT

psql_scalar() {
    docker exec "$container_name" \
        psql -U postgres -d "$database_name" -X -A -t -v ON_ERROR_STOP=1 \
        -c "$1"
}

logical_checksum() {
    local query="$1"
    docker exec "$container_name" \
        psql -U postgres -d "$database_name" -X -A -t -F '|' \
        -v ON_ERROR_STOP=1 -c "$query" \
        | sha256sum \
        | awk '{print $1}'
}

revision="$(psql_scalar 'SELECT version_num FROM alembic_version;')"
users_count="$(psql_scalar 'SELECT count(*) FROM users;')"
groups_count="$(psql_scalar 'SELECT count(*) FROM groups;')"
memberships_count="$(psql_scalar 'SELECT count(*) FROM group_memberships;')"
availability_count="$(psql_scalar 'SELECT count(*) FROM availability;')"

users_sha256="$(logical_checksum \
    "SELECT id::text, display_name, coalesce(email, ''), timezone FROM users ORDER BY id;")"
groups_sha256="$(logical_checksum \
    "SELECT id::text, name, coalesce(description, ''), timezone FROM groups ORDER BY id;")"
memberships_sha256="$(logical_checksum \
    "SELECT group_id::text, user_id::text, role::text, display_order FROM group_memberships ORDER BY group_id, display_order, user_id;")"
availability_sha256="$(logical_checksum \
    "SELECT user_id::text, day::text, status::text FROM availability ORDER BY user_id, day;")"

docker exec "$container_name" \
    pg_dump -U postgres -d "$database_name" \
    --format=custom --compress=6 --no-owner --file=- \
    > "$temporary_dump"

if [[ ! -s "$temporary_dump" ]]; then
    printf 'pg_dump produced an empty archive\n' >&2
    exit 4
fi

docker exec -i "$container_name" pg_restore --list < "$temporary_dump" >/dev/null

{
    printf 'database=%s\n' "$database_name"
    printf 'alembic_revision=%s\n' "$revision"
    printf 'users=%s\n' "$users_count"
    printf 'groups=%s\n' "$groups_count"
    printf 'group_memberships=%s\n' "$memberships_count"
    printf 'availability=%s\n' "$availability_count"
    printf 'users_sha256=%s\n' "$users_sha256"
    printf 'groups_sha256=%s\n' "$groups_sha256"
    printf 'group_memberships_sha256=%s\n' "$memberships_sha256"
    printf 'availability_sha256=%s\n' "$availability_sha256"
} > "$temporary_metadata"

dump_sha256="$(sha256sum "$temporary_dump" | awk '{print $1}')"
(
    set -o noclobber
    printf '%s  %s\n' "$dump_sha256" "$(basename "$dump_path")" \
        > "$temporary_checksum"
)
chmod 0600 "$temporary_dump" "$temporary_metadata" "$temporary_checksum"

mv --no-clobber -- "$temporary_dump" "$dump_path"
mv --no-clobber -- "$temporary_metadata" "$metadata_path"
mv --no-clobber -- "$temporary_checksum" "$checksum_path"

if [[ -e "$temporary_dump" || -e "$temporary_metadata" || -e "$temporary_checksum" ]]; then
    printf 'Backup publication encountered an unexpected destination collision\n' >&2
    exit 5
fi

published=true

trap - EXIT
printf 'backup_path=%s\n' "$dump_path"
printf 'backup_sha256=%s\n' "$dump_sha256"
printf 'metadata_path=%s\n' "$metadata_path"
