#!/usr/bin/env bash

set -Eeuo pipefail

umask 077

readonly app_root="/opt/apps/dnd-planner"
readonly source_dir="${app_root}/source"
readonly runtime_env="${app_root}/runtime.env"
readonly release_file="${app_root}/current_release"
readonly backup_dir="${app_root}/backups"
readonly migrator_password_file="${app_root}/secrets/migrator_password"
readonly compose_file="${source_dir}/deploy/compose.production.yaml"
readonly compose_project="deploy"
readonly network_name="dnd_planner_internal"
readonly backend_container="deploy-backend-1"
readonly frontend_container="deploy-frontend-1"
readonly postgres_container="postgres-postgres-1"
readonly public_url="https://vps-1d46c478.vps.ovh.net"
readonly lock_file="/run/lock/dnd-planner-deploy.lock"

current_release="unknown"
target_release="unknown"
backup_path="not-created"
alembic_before="unknown"
alembic_after="unknown"
migrator_env=""

cleanup() {
    if [[ -n "$migrator_env" ]]; then
        rm -f -- "$migrator_env"
    fi
}

failure_report() {
    local reason="$1"

    printf 'ERROR: %s\n' "$reason" >&2
    printf 'DND PLANNER DEPLOYMENT: FAILED\n' >&2
    printf 'Previous release: %s\n' "$current_release" >&2
    printf 'Target release:   %s\n' "$target_release" >&2
    printf 'PostgreSQL backup: %s\n' "$backup_path" >&2
    printf 'Alembic: %s -> %s\n' "$alembic_before" "$alembic_after" >&2
}

unexpected_error() {
    local status=$?
    local line_number="$1"

    trap - ERR
    failure_report "unexpected failure at line ${line_number}"
    exit "$status"
}

trap cleanup EXIT
trap 'unexpected_error "$LINENO"' ERR

if [[ "$EUID" -ne 0 ]]; then
    failure_report "run this command as root (sudo dnd-deploy)"
    exit 2
fi

exec 9>"$lock_file"
if ! flock -n 9; then
    failure_report "another deployment is already running"
    exit 3
fi

require_file() {
    local path="$1"
    [[ -f "$path" ]] || {
        failure_report "required file is missing: ${path}"
        exit 4
    }
}

require_release_sha() {
    local value="$1"
    local label="$2"

    [[ "$value" =~ ^[0-9a-f]{40}$ ]] || {
        failure_report "${label} is not an exact Git SHA"
        exit 5
    }
}

require_sha256() {
    local value="$1"
    local label="$2"

    [[ "$value" =~ ^[0-9a-f]{64}$ ]] || {
        failure_report "${label} is not a SHA-256 value"
        exit 5
    }
}

container_release() {
    local container="$1"
    local image_prefix="$2"
    local image

    image="$(docker inspect --format '{{.Config.Image}}' "$container")"
    [[ "$image" == "${image_prefix}:"* ]] || return 1
    printf '%s\n' "${image#*:}"
}

container_is_healthy() {
    local container="$1"
    [[ "$(docker inspect --format '{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container")" == "running|healthy" ]]
}

git_source() {
    runuser -u "$source_owner" -- git -C "$source_dir" "$@"
}

compose_release() {
    local release="$1"
    shift
    DND_PLANNER_IMAGE_TAG="$release" \
        DND_PLANNER_ENV_FILE="$runtime_env" \
        MUTATIONS_ENABLED=true \
        docker compose \
            --project-name "$compose_project" \
            --file "$compose_file" \
            "$@"
}

psql_scalar() {
    local query="$1"
    docker exec "$postgres_container" \
        psql -U postgres -d dnd_planner -X -A -t -v ON_ERROR_STOP=1 \
        -c "$query"
}

verify_private_bindings() {
    local backend_ports

    [[ "$(docker port "$frontend_container" 3000/tcp)" == "127.0.0.1:3000" ]]
    [[ "$(docker port "$postgres_container" 5432/tcp)" == "127.0.0.1:5432" ]]
    backend_ports="$(docker port "$backend_container" 8000/tcp || true)"
    [[ -z "$backend_ports" ]]
}

verify_public_https() {
    local status
    status="$(curl --silent --show-error --max-time 10 \
        --output /dev/null --write-out '%{http_code}' "${public_url}/")"
    [[ "$status" == "401" ]]
}

verify_application() {
    container_is_healthy "$postgres_container"
    container_is_healthy "$backend_container"
    container_is_healthy "$frontend_container"
    verify_private_bindings
    systemctl is-active --quiet caddy
    grep -qx 'MUTATIONS_ENABLED=true' < <(
        docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' \
            "$backend_container"
    )
    curl --fail --silent --show-error --max-time 10 \
        --output /dev/null http://127.0.0.1:3000/
    curl --fail --silent --show-error --max-time 10 \
        --output /dev/null http://127.0.0.1:3000/api/test-health
    curl --fail --silent --show-error --max-time 10 \
        --output /dev/null http://127.0.0.1:3000/api/groups
    verify_public_https
}

running_release_matches() {
    local release="$1"
    [[ "$(container_release "$backend_container" dnd-planner-backend)" == "$release" ]]
    [[ "$(container_release "$frontend_container" dnd-planner-frontend)" == "$release" ]]
}

write_release_file() {
    local release="$1"
    local temporary_file

    temporary_file="$(mktemp "${app_root}/.current_release.XXXXXX")"
    printf '%s\n' "$release" > "$temporary_file"
    chown root:root "$temporary_file"
    chmod 0644 "$temporary_file"
    mv -- "$temporary_file" "$release_file"
}

report_manual_intervention() {
    local reason="$1"

    trap - ERR
    printf 'ERROR: %s\n' "$reason" >&2
    printf 'DND PLANNER DEPLOYMENT: FAILED\n' >&2
    printf 'MANUAL INTERVENTION REQUIRED\n' >&2
    printf 'Previous release: %s\n' "$current_release" >&2
    printf 'Target release:   %s\n' "$target_release" >&2
    printf 'PostgreSQL backup: %s\n' "$backup_path" >&2
    printf 'Alembic: %s -> %s\n' "$alembic_before" "$alembic_after" >&2
    exit 1
}

require_file "$runtime_env"
require_file "$migrator_password_file"
require_file "${source_dir}/.git/HEAD"

source_owner="$(stat -c '%U' "$source_dir")"
[[ "$source_owner" != "root" ]] || {
    failure_report "deployment source must be owned by its non-root checkout user"
    exit 6
}

[[ "$(git_source remote get-url origin)" == "https://github.com/BigDedoo/dnd_planner.git" ]] || {
    failure_report "deployment repository origin is not BigDedoo/dnd_planner"
    exit 6
}

if [[ -n "$(git_source status --porcelain --untracked-files=normal)" ]]; then
    failure_report "deployment repository working tree is not clean"
    exit 7
fi

backend_release="$(container_release "$backend_container" dnd-planner-backend)" || {
    failure_report "cannot determine the running backend release"
    exit 8
}
frontend_release="$(container_release "$frontend_container" dnd-planner-frontend)" || {
    failure_report "cannot determine the running frontend release"
    exit 8
}
require_release_sha "$backend_release" "running backend release"
require_release_sha "$frontend_release" "running frontend release"
[[ "$backend_release" == "$frontend_release" ]] || {
    failure_report "running backend and frontend releases differ"
    exit 8
}

if [[ -f "$release_file" ]]; then
    current_release="$(<"$release_file")"
    require_release_sha "$current_release" "current release file"
    [[ "$current_release" == "$backend_release" ]] || {
        failure_report "current release file does not match running images"
        exit 8
    }
else
    current_release="$backend_release"
fi

git_source fetch origin \
    refs/heads/master:refs/remotes/origin/master
if ! target_release="$(git_source rev-parse --verify refs/remotes/origin/master)"; then
    failure_report "origin/master could not be resolved after fetch"
    exit 9
fi
require_release_sha "$target_release" "target release"

if git_source show-ref --verify --quiet refs/heads/master; then
    git_source switch master
    git_source merge --ff-only refs/remotes/origin/master
else
    git_source branch master refs/remotes/origin/master
    git_source switch master
fi

[[ "$(git_source rev-parse HEAD)" == "$target_release" ]] || {
    failure_report "local master did not fast-forward to origin/master"
    exit 9
}
[[ -z "$(git_source status --porcelain --untracked-files=normal)" ]] || {
    failure_report "deployment repository became dirty after synchronization"
    exit 9
}

printf 'CURRENT RELEASE: %s\n' "$current_release"
printf 'TARGET RELEASE:  %s\n' "$target_release"

if [[ "$current_release" == "$target_release" ]]; then
    write_release_file "$current_release"
    trap - ERR
    printf 'DND PLANNER DEPLOYMENT: ALREADY UP TO DATE\n'
    printf 'Release: %s\n' "$current_release"
    exit 0
fi

printf 'Building immutable production images...\n'
if ! compose_release "$target_release" build backend frontend; then
    failure_report "production image build failed; running services were not changed"
    exit 10
fi
docker image inspect "dnd-planner-backend:${target_release}" >/dev/null
docker image inspect "dnd-planner-frontend:${target_release}" >/dev/null

printf 'Checking current production health and private bindings...\n'
if ! verify_application; then
    failure_report "pre-deployment production health check failed"
    exit 11
fi
[[ "$(container_release "$backend_container" dnd-planner-backend)" == "$current_release" ]]
[[ "$(container_release "$frontend_container" dnd-planner-frontend)" == "$current_release" ]]

alembic_before="$(psql_scalar 'SELECT version_num FROM alembic_version;')"

printf 'Creating PostgreSQL backup...\n'
backup_output=""
if ! backup_output="$(BACKUP_DIRECTORY="$backup_dir" \
    POSTGRES_CONTAINER="$postgres_container" \
    "${source_dir}/deploy/backup_postgres.sh" dnd_planner)"; then
    failure_report "PostgreSQL backup failed; database and application were not changed"
    exit 12
fi
backup_path="$(awk -F= '$1 == "backup_path" {print substr($0, index($0, "=") + 1)}' <<< "$backup_output")"
backup_sha256="$(awk -F= '$1 == "backup_sha256" {print $2}' <<< "$backup_output")"
[[ "$backup_path" == "${backup_dir}/"*.dump && -f "$backup_path" ]]
require_sha256 "$backup_sha256" "backup checksum"
(
    cd "$(dirname "$backup_path")"
    sha256sum --check "$(basename "$backup_path").sha256" >/dev/null
)

printf 'Applying Alembic migrations with the migrator role...\n'
migrator_password="$(<"$migrator_password_file")"
encoded_migrator_password="$(printf '%s' "$migrator_password" | python3 -c \
    'import sys; from urllib.parse import quote; print(quote(sys.stdin.read(), safe=""))')"
unset migrator_password
migrator_env="$(mktemp /run/dnd-planner-migrator.XXXXXX)"
{
    printf 'APP_ENV=production\n'
    printf 'LOG_LEVEL=INFO\n'
    printf 'DATABASE_URL=postgresql+psycopg://dnd_planner_migrator:%s@postgres:5432/dnd_planner\n' \
        "$encoded_migrator_password"
} > "$migrator_env"
unset encoded_migrator_password
chmod 0600 "$migrator_env"

if ! docker run --rm \
    --network "$network_name" \
    --env-file "$migrator_env" \
    --entrypoint alembic \
    "dnd-planner-backend:${target_release}" upgrade head; then
    alembic_after="$(psql_scalar 'SELECT version_num FROM alembic_version;' || printf 'unknown')"
    if [[ "$alembic_after" != "$alembic_before" ]]; then
        report_manual_intervention "Alembic migration failed after the recorded revision changed"
    fi
    failure_report "Alembic migration failed; the current application remains running"
    exit 13
fi
rm -f -- "$migrator_env"
migrator_env=""

alembic_after="$(psql_scalar 'SELECT version_num FROM alembic_version;')"
if [[ "$alembic_before" == "$alembic_after" ]]; then
    printf 'DATABASE SCHEMA: UNCHANGED\n'
else
    printf 'DATABASE SCHEMA: %s -> %s\n' "$alembic_before" "$alembic_after"
fi

printf 'Starting target application release...\n'
deployment_ok=true
if ! compose_release "$target_release" up --detach --no-build --wait \
    --wait-timeout 180 backend frontend; then
    deployment_ok=false
elif ! verify_application; then
    deployment_ok=false
elif ! running_release_matches "$target_release"; then
    deployment_ok=false
fi

if [[ "$deployment_ok" != true ]]; then
    if [[ "$alembic_before" != "$alembic_after" ]]; then
        report_manual_intervention "target application health failed after a database migration"
    fi

    printf 'Target health failed; restoring previous application images...\n' >&2
    rollback_ok=true
    if ! compose_release "$current_release" up --detach --no-build --wait \
        --wait-timeout 180 backend frontend; then
        rollback_ok=false
    elif ! verify_application; then
        rollback_ok=false
    elif ! running_release_matches "$current_release"; then
        rollback_ok=false
    fi

    if [[ "$rollback_ok" == true ]]; then
        trap - ERR
        printf 'DND PLANNER DEPLOYMENT: ROLLED BACK\n' >&2
        printf 'Release: %s\n' "$current_release" >&2
        printf 'Failed target: %s\n' "$target_release" >&2
        printf 'PostgreSQL backup: %s\n' "$backup_path" >&2
        printf 'Alembic: %s -> %s\n' "$alembic_before" "$alembic_after" >&2
        exit 1
    fi

    report_manual_intervention "target and rollback application health checks failed"
fi

write_release_file "$target_release"
trap - ERR

printf 'DND PLANNER DEPLOYMENT: LIVE\n'
printf 'Previous release: %s\n' "$current_release"
printf 'Current release:  %s\n' "$target_release"
printf 'PostgreSQL backup: %s\n' "$backup_path"
printf 'Alembic: %s -> %s\n' "$alembic_before" "$alembic_after"
printf 'Backend: healthy\n'
printf 'Frontend: healthy\n'
printf 'PostgreSQL: healthy\n'
printf 'HTTPS: healthy\n'
