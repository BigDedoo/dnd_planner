#!/usr/bin/env bash

set -euo pipefail
umask 077

if [[ $# -ne 1 ]]; then
    printf 'Usage: %s /absolute/path/to/backup.dump\n' "$0" >&2
    exit 2
fi

dump_path="$1"
checksum_path="${dump_path}.sha256"
metadata_path="${dump_path}.metadata"
container_name="${POSTGRES_CONTAINER:-postgres-postgres-1}"
migrator_role="${MIGRATOR_ROLE:-dnd_planner_migrator}"
database_name="dnd_planner_restore_validation_$(openssl rand -hex 8)"
created=false

for required_path in "$dump_path" "$checksum_path" "$metadata_path"; do
    if [[ ! -f "$required_path" ]]; then
        printf 'Required restore artifact is missing: %s\n' "$required_path" >&2
        exit 2
    fi
done

if [[ ! "$database_name" =~ ^dnd_planner_restore_validation_[a-f0-9]{16}$ ]]; then
    printf 'Generated an unsafe restore database name\n' >&2
    exit 3
fi

(
    cd -- "$(dirname -- "$dump_path")"
    sha256sum --check --status "$(basename -- "$checksum_path")"
)

declare -A expected
while IFS='=' read -r key value; do
    case "$key" in
        database|alembic_revision|users|groups|group_memberships|availability|\
        users_sha256|groups_sha256|group_memberships_sha256|availability_sha256)
            expected["$key"]="$value"
            ;;
        *)
            printf 'Unknown metadata key: %s\n' "$key" >&2
            exit 4
            ;;
    esac
done < "$metadata_path"

cleanup_database() {
    if [[ "$created" != true ]]; then
        return
    fi
    docker exec "$container_name" psql -U postgres -d postgres \
        -X -v ON_ERROR_STOP=1 \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${database_name}' AND pid <> pg_backend_pid();" \
        >/dev/null 2>&1 || true
    docker exec "$container_name" psql -U postgres -d postgres \
        -X -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS \"${database_name}\";" \
        >/dev/null 2>&1 || true
}
trap cleanup_database EXIT

existing="$(docker exec "$container_name" psql -U postgres -d postgres \
    -X -A -t -v ON_ERROR_STOP=1 \
    -c "SELECT count(*) FROM pg_database WHERE datname = '${database_name}';")"
if [[ "$existing" != "0" ]]; then
    printf 'Generated restore database unexpectedly exists\n' >&2
    exit 5
fi

docker exec "$container_name" psql -U postgres -d postgres \
    -X -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE \"${database_name}\" OWNER \"${migrator_role}\";" \
    >/dev/null
created=true

docker exec -i "$container_name" pg_restore \
    -U postgres -d "$database_name" --exit-on-error \
    --no-owner --role="$migrator_role" \
    < "$dump_path"

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

declare -A actual
actual[alembic_revision]="$(psql_scalar 'SELECT version_num FROM alembic_version;')"
actual[users]="$(psql_scalar 'SELECT count(*) FROM users;')"
actual[groups]="$(psql_scalar 'SELECT count(*) FROM groups;')"
actual[group_memberships]="$(psql_scalar 'SELECT count(*) FROM group_memberships;')"
actual[availability]="$(psql_scalar 'SELECT count(*) FROM availability;')"
actual[users_sha256]="$(logical_checksum \
    "SELECT id::text, display_name, coalesce(email, ''), timezone FROM users ORDER BY id;")"
actual[groups_sha256]="$(logical_checksum \
    "SELECT id::text, name, coalesce(description, ''), timezone FROM groups ORDER BY id;")"
actual[group_memberships_sha256]="$(logical_checksum \
    "SELECT group_id::text, user_id::text, role::text, display_order FROM group_memberships ORDER BY group_id, display_order, user_id;")"
actual[availability_sha256]="$(logical_checksum \
    "SELECT user_id::text, day::text, status::text FROM availability ORDER BY user_id, day;")"

for key in \
    alembic_revision users groups group_memberships availability \
    users_sha256 groups_sha256 group_memberships_sha256 availability_sha256; do
    if [[ "${actual[$key]}" != "${expected[$key]:-}" ]]; then
        printf 'Restore verification mismatch for %s: expected=%s actual=%s\n' \
            "$key" "${expected[$key]:-missing}" "${actual[$key]}" >&2
        exit 6
    fi
done

printf 'restore_database=%s\n' "$database_name"
printf 'alembic_revision=%s\n' "${actual[alembic_revision]}"
printf 'users=%s groups=%s memberships=%s availability=%s\n' \
    "${actual[users]}" "${actual[groups]}" \
    "${actual[group_memberships]}" "${actual[availability]}"
printf 'availability_sha256=%s\n' "${actual[availability_sha256]}"
printf 'restore_verification=passed\n'
