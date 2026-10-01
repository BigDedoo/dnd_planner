#!/usr/bin/env bash

# Synthetic files and exported command doubles only: no Docker, SSH, rsync
# network traffic, systemd changes, database access, or real heartbeat URLs.
set -euo pipefail
export LC_ALL=C
repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
test_directory="$(mktemp -d /tmp/dnd-heartbeats.XXXXXXXX)"
cleanup() {
    [[ "$test_directory" == /tmp/dnd-heartbeats.* && -d "$test_directory" ]] || return
    command rm -rf -- "$test_directory"
}
trap cleanup EXIT
helper="${repo_root}/deploy/backup_success_heartbeat.sh"
credential_directory="${test_directory}/credentials"
mkdir "$credential_directory"
export CREDENTIALS_DIRECTORY="$credential_directory"
export TEST_CALLS="${test_directory}/curl-args"
export TEST_CONFIG="${test_directory}/curl-config"
export TEST_CURL_FAILURE=0 TEST_REQUIRED_MARKER="" TEST_PRUNED_PATH=""
fixture_url='https://example.invalid/heartbeat/synthetic-only'
warning='Warning: backup succeeded but monitoring heartbeat delivery failed'
checks=0

curl() {
    printf '%s\n' "$@" >"$TEST_CALLS"
    command cat >"$TEST_CONFIG"
    if [[ -n "$TEST_REQUIRED_MARKER" && ! -f "$TEST_REQUIRED_MARKER" ]]; then
        return 70
    fi
    if [[ -n "$TEST_PRUNED_PATH" && -e "$TEST_PRUNED_PATH" ]]; then
        return 71
    fi
    if [[ "$TEST_CURL_FAILURE" != 0 ]]; then
        # Even a noisy client must not leak configuration/response data.
        command cat "$TEST_CONFIG"
        command cat "$TEST_CONFIG" >&2
        return 7
    fi
    printf '%s' "${TEST_HTTP_STATUS:-200}"
}
export -f curl

check() {
    if ! "$@"; then
        printf 'Heartbeat test failed: assertion %s\n' "$((checks + 1))" >&2
        exit 1
    fi
    checks="$((checks + 1))"
}
clear_calls() { command rm -f -- "$TEST_CALLS" "$TEST_CONFIG"; }
expect_helper_failure() {
    clear_calls
    if bash "$helper" >"${test_directory}/helper-output" 2>&1; then
        return 1
    fi
    [[ ! -e "$TEST_CALLS" && ! -s "${test_directory}/helper-output" ]]
}

# Missing credentials remain optional, including a missing credential directory.
check bash "$helper"
check test ! -e "$TEST_CALLS"
check env -u CREDENTIALS_DIRECTORY bash "$helper"
printf '%s\n' "$fixture_url" >"${credential_directory}/betterstack_heartbeat"
check bash "$helper"
check test -s "$TEST_CALLS"
check grep -Fxq -- '--config' "$TEST_CALLS"
check grep -Fxq -- '=https' "$TEST_CALLS"
check grep -Fxq -- '10' "$TEST_CALLS"
check grep -Fxq -- '--retry-max-time' "$TEST_CALLS"
check test "$(head -n 1 "$TEST_CALLS")" = '-q'
check test "$(command cat "$TEST_CONFIG")" = "url = \"${fixture_url}\""
check test "$(grep -Fc -- "$fixture_url" "$TEST_CALLS" || true)" = 0
check test "$(grep -Ec -- '--location|--verbose|--trace' "$TEST_CALLS" || true)" = 0
check bash -x "$helper" >"${test_directory}/trace" 2>&1
check test "$(grep -Fc -- "$fixture_url" "${test_directory}/trace" || true)" = 0

for malformed in '' 'http://example.invalid/heartbeat' \
    $'https://example.invalid/one\nhttps://example.invalid/two' \
    $'https://example.invalid/one\r' \
    $'https://example.invalid/one\n\n' \
    'https://example.invalid/"injection' 'https://example.invalid/\injection'; do
    printf '%s' "$malformed" >"${credential_directory}/betterstack_heartbeat"
    check expect_helper_failure
done
printf '%s\0' "$fixture_url" >"${credential_directory}/betterstack_heartbeat"
check expect_helper_failure
command rm "${credential_directory}/betterstack_heartbeat"
printf '%s' "$fixture_url" >"${test_directory}/symlink-target"
ln -s "${test_directory}/symlink-target" "${credential_directory}/betterstack_heartbeat"
check expect_helper_failure
command rm "${credential_directory}/betterstack_heartbeat"
mkdir "${credential_directory}/betterstack_heartbeat"
check expect_helper_failure
rmdir "${credential_directory}/betterstack_heartbeat"
printf '%s' "$fixture_url" >"${credential_directory}/betterstack_heartbeat"
export TEST_HTTP_STATUS=302
if bash "$helper"; then
    printf 'Unexpected redirect accepted\n' >&2
    exit 1
fi
checks="$((checks + 1))"
unset TEST_HTTP_STATUS

# Exercise both actual success paths with synthetic backup sets and command
# doubles only for ownership, backup creation, transfer, and curl.
make_set() {
    local directory="$1" name="$2"
    mkdir -p "$directory"
    printf 'synthetic archive\n' >"${directory}/${name}.dump"
    (cd "$directory" && sha256sum "${name}.dump" >"${name}.dump.sha256")
    printf 'synthetic metadata\n' >"${directory}/${name}.dump.metadata"
}
new_name='dnd_planner-20990101T000000000000000Z'
old_name='dnd_planner-20000101T000000000000000Z'
export TEST_NEW_NAME="$new_name" TEST_BACKUP_FAILURE=0 TEST_TRANSFER_FAILURE=0
export TEST_RETENTION_FAILURE=0
cat >"${test_directory}/backup" <<'FIXTURE'
#!/usr/bin/env bash
set -euo pipefail
[[ "$TEST_BACKUP_FAILURE" == 0 ]] || exit 8
name="$TEST_NEW_NAME"
for suffix in dump dump.sha256 dump.metadata; do
    if [[ -f "${BACKUP_DIRECTORY}/${name}.${suffix}" ]]; then
        chmod 0600 "${BACKUP_DIRECTORY}/${name}.${suffix}"
    fi
done
printf 'synthetic archive\n' >"${BACKUP_DIRECTORY}/${name}.dump"
(cd "$BACKUP_DIRECTORY" && sha256sum "${name}.dump" >"${name}.dump.sha256")
printf 'synthetic metadata\n' >"${BACKUP_DIRECTORY}/${name}.dump.metadata"
printf 'backup_path=%s\n' "${BACKUP_DIRECTORY}/${name}.dump"
printf 'backup_sha256=%s\n' "$(sha256sum "${BACKUP_DIRECTORY}/${name}.dump" | cut -d ' ' -f 1)"
printf 'metadata_path=%s\n' "${BACKUP_DIRECTORY}/${name}.dump.metadata"
FIXTURE
chmod 0700 "${test_directory}/backup"
install() {
    if [[ "$1" == '-d' && "$2" == '-o' ]]; then
        command install -d -m 0750 "${@: -1}"
    else
        command install "$@"
    fi
}
chown() { return 0; }
rm() {
    [[ "$TEST_RETENTION_FAILURE" == 0 ]] || return 8
    command rm "$@"
}
rsync() {
    [[ "$TEST_TRANSFER_FAILURE" == 0 ]] || return 8
    command cp "${TEST_TRANSFER_DIRECTORY}/"* "${@: -1}"
}
export -f install chown rm rsync
export BACKUP_SCRIPT="${test_directory}/backup"
export DAILY_BACKUP_DIRECTORY="${test_directory}/daily"
export DEPLOYMENT_LOCK_FILE="${test_directory}/deployment.lock"
export OFFSITE_BACKUP_GROUP="$(id -gn)"
make_set "$DAILY_BACKUP_DIRECTORY" "$old_name"
touch -d '100 days ago' "${DAILY_BACKUP_DIRECTORY}/${old_name}.dump"
export TEST_REQUIRED_MARKER="${DAILY_BACKUP_DIRECTORY}/${new_name}.dump"
export TEST_PRUNED_PATH="${DAILY_BACKUP_DIRECTORY}/${old_name}.dump"
clear_calls
check bash "${repo_root}/deploy/routine_backup_postgres.sh" >"${test_directory}/vps-output" 2>&1
check test -s "$TEST_CALLS"
check test ! -e "$TEST_PRUNED_PATH"
check test "$(stat -c '%a' "$TEST_REQUIRED_MARKER")" = 440
export TEST_CURL_FAILURE=1
check bash "${repo_root}/deploy/routine_backup_postgres.sh" >"${test_directory}/vps-output" 2>&1
check grep -Fxq "$warning" "${test_directory}/vps-output"
check test "$(grep -Fc -- "$fixture_url" "${test_directory}/vps-output" || true)" = 0
export TEST_CURL_FAILURE=0 TEST_BACKUP_FAILURE=1
clear_calls
if bash "${repo_root}/deploy/routine_backup_postgres.sh" >"${test_directory}/vps-output" 2>&1; then exit 1; fi
check test ! -e "$TEST_CALLS"
export TEST_BACKUP_FAILURE=0 TEST_RETENTION_FAILURE=1
make_set "$DAILY_BACKUP_DIRECTORY" "$old_name"
touch -d '100 days ago' "${DAILY_BACKUP_DIRECTORY}/${old_name}.dump"
clear_calls
if bash "${repo_root}/deploy/routine_backup_postgres.sh" >"${test_directory}/vps-output" 2>&1; then exit 1; fi
check test ! -e "$TEST_CALLS"
export TEST_RETENTION_FAILURE=0
printf 'http://example.invalid/invalid' >"${credential_directory}/betterstack_heartbeat"
check bash "${repo_root}/deploy/routine_backup_postgres.sh" >"${test_directory}/vps-output" 2>&1
check grep -Fxq "$warning" "${test_directory}/vps-output"
check test ! -e "$TEST_CALLS"
printf '%s' "$fixture_url" >"${credential_directory}/betterstack_heartbeat"
command rm "${credential_directory}/betterstack_heartbeat"
clear_calls
check bash "${repo_root}/deploy/routine_backup_postgres.sh" >"${test_directory}/vps-output" 2>&1
check test ! -e "$TEST_CALLS"
check test "$(grep -Fc -- "$warning" "${test_directory}/vps-output" || true)" = 0
printf '%s' "$fixture_url" >"${credential_directory}/betterstack_heartbeat"

export DND_BACKUP_DIRECTORY="${test_directory}/offsite"
export RUNTIME_DIRECTORY="${test_directory}/runtime"
export DND_BACKUP_IDENTITY_FILE="${test_directory}/fake-key"
export DND_BACKUP_KNOWN_HOSTS_FILE="${test_directory}/fake-known-hosts"
export TEST_TRANSFER_DIRECTORY="${test_directory}/transfer"
mkdir "$DND_BACKUP_DIRECTORY" "$RUNTIME_DIRECTORY"
touch "$DND_BACKUP_IDENTITY_FILE" "$DND_BACKUP_KNOWN_HOSTS_FILE"
make_set "$TEST_TRANSFER_DIRECTORY" "$new_name"
make_set "${DND_BACKUP_DIRECTORY}/${old_name}" "$old_name"
touch -d '100 days ago' "${DND_BACKUP_DIRECTORY}/${old_name}"
export TEST_REQUIRED_MARKER="${DND_BACKUP_DIRECTORY}/LAST_SUCCESS"
export TEST_PRUNED_PATH="${DND_BACKUP_DIRECTORY}/${old_name}"
clear_calls
check bash "${repo_root}/deploy/pull_postgres_backups.sh" >"${test_directory}/pi-output" 2>&1
check test -s "$TEST_CALLS"
check test -f "$TEST_REQUIRED_MARKER"
check test ! -e "$TEST_PRUNED_PATH"
export TEST_CURL_FAILURE=1
check bash "${repo_root}/deploy/pull_postgres_backups.sh" >"${test_directory}/pi-output" 2>&1
check grep -Fxq "$warning" "${test_directory}/pi-output"
check test "$(grep -Fc -- "$fixture_url" "${test_directory}/pi-output" || true)" = 0
export TEST_CURL_FAILURE=0 TEST_TRANSFER_FAILURE=1
clear_calls
if bash "${repo_root}/deploy/pull_postgres_backups.sh" >"${test_directory}/pi-output" 2>&1; then exit 1; fi
check test ! -e "$TEST_CALLS"
export TEST_TRANSFER_FAILURE=0
# Existing sets are excluded from rsync in real operation. Corruption in the
# newest already-archived dump must still prevent LAST_SUCCESS/heartbeat.
rsync() { return 0; }
export -f rsync
printf 'corrupted\n' >"${DND_BACKUP_DIRECTORY}/${new_name}/${new_name}.dump"
command rm "$TEST_REQUIRED_MARKER"
clear_calls
if bash "${repo_root}/deploy/pull_postgres_backups.sh" >"${test_directory}/pi-output" 2>&1; then exit 1; fi
check test ! -e "$TEST_CALLS"
check test ! -e "$TEST_REQUIRED_MARKER"

printf 'Backup heartbeat tests: %s assertions passed (synthetic only)\n' "$checks"
