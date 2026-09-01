#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

remote_host="${DND_BACKUP_REMOTE_HOST:-152.228.237.169}"
remote_user="${DND_BACKUP_REMOTE_USER:-dnd-backup}"
identity_file="${DND_BACKUP_IDENTITY_FILE:-/var/lib/dnd-backup/.ssh/id_ed25519}"
known_hosts_file="${DND_BACKUP_KNOWN_HOSTS_FILE:-/var/lib/dnd-backup/.ssh/known_hosts}"
backup_directory="${DND_BACKUP_DIRECTORY:-/srv/backups/dnd-planner-postgres}"
incoming_directory="${backup_directory}/.incoming"
runtime_directory="${RUNTIME_DIRECTORY:-/run/dnd-planner-offsite-backup}"
lock_file="${runtime_directory}/pull.lock"
retention_days="${RASPBERRY_BACKUP_RETENTION_DAYS:-90}"

if [[ ! "$retention_days" =~ ^[1-9][0-9]*$ ]]; then
    printf 'Invalid Raspberry backup retention: %s\n' "$retention_days" >&2
    exit 2
fi
for required_file in "$identity_file" "$known_hosts_file"; do
    if [[ ! -f "$required_file" || -L "$required_file" ]]; then
        printf 'Required SSH file is missing or unsafe: %s\n' "$required_file" >&2
        exit 2
    fi
done
for required_directory in "$backup_directory" "$runtime_directory"; do
    if [[ ! -d "$required_directory" || -L "$required_directory" ]]; then
        printf 'Required directory is missing or unsafe: %s\n' \
            "$required_directory" >&2
        exit 2
    fi
done
install -d -m 0700 "$incoming_directory"

exec 9>"$lock_file"
if ! flock -n 9; then
    printf 'Another DnD Planner off-site pull is already running\n' >&2
    exit 3
fi

exclude_file="${runtime_directory}/rsync-excludes"
: >"$exclude_file"
while IFS= read -r archived_set; do
    set_name="$(basename "$archived_set")"
    [[ "$set_name" =~ ^dnd_planner-[0-9]{8}T[0-9]{15}Z$ ]] || continue
    printf '/%s.dump\n/%s.dump.sha256\n/%s.dump.metadata\n' \
        "$set_name" "$set_name" "$set_name" >>"$exclude_file"
done < <(
    find -P "$backup_directory" -mindepth 1 -maxdepth 1 -type d \
        -name 'dnd_planner-*Z' -print | sort
)

ssh_transport="ssh -i ${identity_file} -o BatchMode=yes -o IdentitiesOnly=yes"
ssh_transport+=" -o StrictHostKeyChecking=yes"
ssh_transport+=" -o UserKnownHostsFile=${known_hosts_file}"
ssh_transport+=" -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no"

rsync \
    --recursive \
    --times \
    --ignore-existing \
    --partial \
    --partial-dir=.rsync-partial \
    --chmod=F600,D700 \
    --exclude-from="$exclude_file" \
    --include='/dnd_planner-*.dump' \
    --include='/dnd_planner-*.dump.sha256' \
    --include='/dnd_planner-*.dump.metadata' \
    --exclude='*' \
    -e "$ssh_transport" \
    "${remote_user}@${remote_host}:/" \
    "${incoming_directory}/"

publish_directory=""
status_temporary=""
cleanup() {
    if [[ -n "$publish_directory" && -d "$publish_directory" ]]; then
        find -P "$publish_directory" -maxdepth 1 -type f -delete
        rmdir "$publish_directory" 2>/dev/null || true
    fi
    if [[ -n "$status_temporary" ]]; then
        rm -f -- "$status_temporary"
    fi
}
trap cleanup EXIT

received_sets=0
while IFS= read -r -d '' incoming_dump; do
    dump_name="$(basename "$incoming_dump")"
    if [[ ! "$dump_name" =~ ^dnd_planner-[0-9]{8}T[0-9]{15}Z\.dump$ ]]; then
        printf 'Unexpected incoming backup filename: %s\n' "$dump_name" >&2
        exit 4
    fi
    set_name="${dump_name%.dump}"
    incoming_checksum="${incoming_dump}.sha256"
    incoming_metadata="${incoming_dump}.metadata"
    for artifact in "$incoming_dump" "$incoming_checksum" "$incoming_metadata"; do
        if [[ ! -f "$artifact" || -L "$artifact" || ! -s "$artifact" ]]; then
            printf 'Incomplete incoming backup set: %s\n' "$set_name" >&2
            exit 4
        fi
    done

    if [[ "$(wc -l <"$incoming_checksum")" -ne 1 ]]; then
        printf 'Invalid checksum manifest for %s\n' "$set_name" >&2
        exit 4
    fi
    read -r expected_sha256 expected_name <"$incoming_checksum"
    if [[ ! "$expected_sha256" =~ ^[0-9a-f]{64}$ \
        || "$expected_name" != "$dump_name" ]]; then
        printf 'Checksum manifest does not match %s\n' "$dump_name" >&2
        exit 4
    fi
    (
        cd "$incoming_directory"
        sha256sum --check --strict "$(basename "$incoming_checksum")" >/dev/null
    )

    final_directory="${backup_directory}/${set_name}"
    if [[ -e "$final_directory" ]]; then
        if [[ ! -d "$final_directory" || -L "$final_directory" ]]; then
            printf 'Archive destination is unsafe: %s\n' "$final_directory" >&2
            exit 4
        fi
        final_dump="${final_directory}/${dump_name}"
        final_checksum="${final_directory}/${dump_name}.sha256"
        final_metadata="${final_directory}/${dump_name}.metadata"
        for artifact in "$final_dump" "$final_checksum" "$final_metadata"; do
            if [[ ! -f "$artifact" || -L "$artifact" || ! -s "$artifact" ]]; then
                printf 'Existing archive set is incomplete: %s\n' "$set_name" >&2
                exit 4
            fi
        done
        if ! cmp -s "$incoming_checksum" "$final_checksum"; then
            printf 'Existing archive checksum differs for %s\n' "$set_name" >&2
            exit 4
        fi
        (
            cd "$final_directory"
            sha256sum --check --strict "$(basename "$final_checksum")" >/dev/null
        )
        rm -- "$incoming_dump" "$incoming_checksum" "$incoming_metadata"
        continue
    fi

    publish_directory="${backup_directory}/.publish-${set_name}.$$"
    mkdir -m 0700 "$publish_directory"
    install -m 0600 "$incoming_dump" "${publish_directory}/${dump_name}"
    install -m 0600 "$incoming_checksum" \
        "${publish_directory}/${dump_name}.sha256"
    install -m 0600 "$incoming_metadata" \
        "${publish_directory}/${dump_name}.metadata"
    (
        cd "$publish_directory"
        sha256sum --check --strict "${dump_name}.sha256" >/dev/null
    )
    mv -- "$publish_directory" "$final_directory"
    publish_directory=""
    rm -- "$incoming_dump" "$incoming_checksum" "$incoming_metadata"
    received_sets="$((received_sets + 1))"
done < <(
    find -P "$incoming_directory" -maxdepth 1 -type f \
        -name 'dnd_planner-*.dump' -print0 | sort -z
)

if find -P "$incoming_directory" -maxdepth 1 -type f \
    -name 'dnd_planner-*' -print -quit | grep -q .; then
    printf 'Unverified incoming backup artifacts remain\n' >&2
    exit 4
fi

retention_minutes="$((retention_days * 24 * 60))"
pruned_sets=0
while IFS= read -r -d '' old_set; do
    old_name="$(basename "$old_set")"
    [[ "$old_name" =~ ^dnd_planner-[0-9]{8}T[0-9]{15}Z$ ]] || continue
    old_dump="${old_set}/${old_name}.dump"
    old_checksum="${old_dump}.sha256"
    old_metadata="${old_dump}.metadata"
    file_count="$(find -P "$old_set" -maxdepth 1 -type f | wc -l)"
    if [[ "$file_count" -eq 3 \
        && -f "$old_dump" && ! -L "$old_dump" \
        && -f "$old_checksum" && ! -L "$old_checksum" \
        && -f "$old_metadata" && ! -L "$old_metadata" ]]; then
        rm -- "$old_dump" "$old_checksum" "$old_metadata"
        rmdir "$old_set"
        pruned_sets="$((pruned_sets + 1))"
    fi
done < <(
    find -P "$backup_directory" -mindepth 1 -maxdepth 1 -type d \
        -name 'dnd_planner-*Z' -mmin "+${retention_minutes}" -print0
)

newest_set="$(
    find -P "$backup_directory" -mindepth 1 -maxdepth 1 -type d \
        -name 'dnd_planner-*Z' -printf '%f\n' | sort | tail -n 1
)"
if [[ ! "$newest_set" =~ ^dnd_planner-[0-9]{8}T[0-9]{15}Z$ ]]; then
    printf 'No verified off-site backup is available\n' >&2
    exit 5
fi
newest_checksum_file="${backup_directory}/${newest_set}/${newest_set}.dump.sha256"
read -r newest_sha256 newest_filename <"$newest_checksum_file"
if [[ ! "$newest_sha256" =~ ^[0-9a-f]{64}$ \
    || "$newest_filename" != "${newest_set}.dump" ]]; then
    printf 'Newest archive checksum manifest is invalid\n' >&2
    exit 5
fi

status_temporary="${backup_directory}/.LAST_SUCCESS.$$"
{
    printf 'utc_timestamp=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'newest_backup=%s\n' "$newest_filename"
    printf 'sha256=%s\n' "$newest_sha256"
} >"$status_temporary"
chmod 0600 "$status_temporary"
mv -- "$status_temporary" "${backup_directory}/LAST_SUCCESS"
status_temporary=""

trap - EXIT
printf 'received_sets=%s\n' "$received_sets"
printf 'newest_backup=%s\n' "$newest_filename"
printf 'raspberry_retention_days=%s\n' "$retention_days"
printf 'pruned_sets=%s\n' "$pruned_sets"
printf 'last_success=%s\n' "${backup_directory}/LAST_SUCCESS"
