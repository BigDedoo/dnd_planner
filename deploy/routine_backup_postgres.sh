#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

app_root="${DND_PLANNER_APP_ROOT:-/opt/apps/dnd-planner}"
backup_script="${BACKUP_SCRIPT:-${app_root}/source/deploy/backup_postgres.sh}"
daily_directory="${DAILY_BACKUP_DIRECTORY:-${app_root}/backups/daily}"
deployment_lock="${DEPLOYMENT_LOCK_FILE:-/run/lock/dnd-planner-deploy.lock}"
postgres_container="${POSTGRES_CONTAINER:-postgres-postgres-1}"
offsite_group="${OFFSITE_BACKUP_GROUP:-dnd-backup}"
retention_days="${VPS_BACKUP_RETENTION_DAYS:-14}"
lock_wait_seconds="${BACKUP_LOCK_WAIT_SECONDS:-3600}"

if [[ ! "$retention_days" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Invalid VPS backup retention: %s\n' "$retention_days" >&2
    exit 2
fi
if [[ ! "$lock_wait_seconds" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Invalid deployment-lock wait: %s\n' "$lock_wait_seconds" >&2
    exit 2
fi
if [[ ! -x "$backup_script" ]]; then
    printf 'Backup implementation is unavailable: %s\n' "$backup_script" >&2
    exit 2
fi
if ! getent group "$offsite_group" >/dev/null; then
    printf 'Off-site backup group is unavailable: %s\n' "$offsite_group" >&2
    exit 2
fi

install -d -o root -g "$offsite_group" -m 0750 "$daily_directory"

exec 9>"$deployment_lock"
if ! flock -w "$lock_wait_seconds" 9; then
    printf 'Timed out waiting for the DnD Planner deployment lock\n' >&2
    exit 3
fi

backup_output="$(
    BACKUP_DIRECTORY="$daily_directory" \
        POSTGRES_CONTAINER="$postgres_container" \
        "$backup_script" dnd_planner
)"
backup_path="$(
    awk -F= '$1 == "backup_path" {print substr($0, index($0, "=") + 1)}' \
        <<<"$backup_output"
)"
backup_sha256="$(
    awk -F= '$1 == "backup_sha256" {print $2}' <<<"$backup_output"
)"
metadata_path="$(
    awk -F= '$1 == "metadata_path" {print substr($0, index($0, "=") + 1)}' \
        <<<"$backup_output"
)"
checksum_path="${backup_path}.sha256"

if [[ ! "$backup_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'Backup implementation returned an invalid SHA-256\n' >&2
    exit 4
fi
if [[ "$backup_path" != "${daily_directory}/"*.dump ]]; then
    printf 'Backup implementation returned an unexpected path\n' >&2
    exit 4
fi
backup_name="$(basename "$backup_path")"
if [[ ! "$backup_name" =~ ^dnd_planner-[0-9]{8}T[0-9]{15}Z\.dump$ ]]; then
    printf 'Backup implementation returned an unexpected filename\n' >&2
    exit 4
fi
if [[ "$metadata_path" != "${backup_path}.metadata" ]]; then
    printf 'Backup implementation returned an unexpected metadata path\n' >&2
    exit 4
fi

for artifact in "$backup_path" "$checksum_path" "$metadata_path"; do
    if [[ ! -f "$artifact" || -L "$artifact" || ! -s "$artifact" ]]; then
        printf 'Backup artifact is missing, empty, or unsafe: %s\n' "$artifact" >&2
        exit 4
    fi
done

(
    cd "$daily_directory"
    sha256sum --check --strict "$(basename "$checksum_path")" >/dev/null
)
if [[ "$(sha256sum "$backup_path" | awk '{print $1}')" != "$backup_sha256" ]]; then
    printf 'Backup checksum does not match the reported SHA-256\n' >&2
    exit 4
fi

chown root:"$offsite_group" "$backup_path" "$checksum_path" "$metadata_path"
chmod 0440 "$backup_path" "$checksum_path" "$metadata_path"

retention_minutes="$((retention_days * 24 * 60))"
pruned_sets=0
while IFS= read -r -d '' old_dump; do
    [[ "$old_dump" != "$backup_path" ]] || continue
    old_name="$(basename "$old_dump")"
    [[ "$old_name" =~ ^dnd_planner-[0-9]{8}T[0-9]{15}Z\.dump$ ]] || continue
    old_checksum="${old_dump}.sha256"
    old_metadata="${old_dump}.metadata"
    if [[ -f "$old_checksum" && ! -L "$old_checksum" \
        && -f "$old_metadata" && ! -L "$old_metadata" ]]; then
        rm -- "$old_dump" "$old_checksum" "$old_metadata"
        pruned_sets="$((pruned_sets + 1))"
    fi
done < <(
    find -P "$daily_directory" -maxdepth 1 -type f \
        -name 'dnd_planner-*.dump' -mmin "+${retention_minutes}" -print0
)

printf 'backup_path=%s\n' "$backup_path"
printf 'backup_sha256=%s\n' "$backup_sha256"
printf 'metadata_path=%s\n' "$metadata_path"
printf 'vps_retention_days=%s\n' "$retention_days"
printf 'pruned_sets=%s\n' "$pruned_sets"
