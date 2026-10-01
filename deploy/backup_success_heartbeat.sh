#!/usr/bin/env bash

# Called only by a completed backup. The caller converts failure to a generic
# warning. Never trace credential reads, curl configuration, or response data.
set +x
set +a
set -euo pipefail
export LC_ALL=C

if [[ -z "${CREDENTIALS_DIRECTORY:-}" ]]; then
    exit 0
fi
credential_file="${CREDENTIALS_DIRECTORY}/betterstack_heartbeat"
if [[ ! -e "$credential_file" && ! -L "$credential_file" ]]; then
    exit 0
fi
if [[ ! -f "$credential_file" || -L "$credential_file" \
    || ! -s "$credential_file" || ! -r "$credential_file" ]]; then
    exit 1
fi

# Read without command substitution (which would discard all trailing LFs).
# A NUL terminator is invalid; allow only one optional final LF from sudoedit.
if IFS= read -r -d '' heartbeat_url <"$credential_file"; then
    exit 1
fi
heartbeat_url="${heartbeat_url%$'\n'}"
if [[ -z "$heartbeat_url" || ${#heartbeat_url} -gt 4096 \
    || "$heartbeat_url" != https://?* \
    || "$heartbeat_url" == *[[:space:][:cntrl:]]* \
    || "$heartbeat_url" == *'"'* || "$heartbeat_url" == *'\'* ]]; then
    exit 1
fi

# -q must be first: ignore any user curlrc. No redirects, verbose output, URL
# in argv, or response body. At most two attempts, each bounded to 10 seconds.
http_status="$(
    printf 'url = "%s"\n' "$heartbeat_url" |
        curl -q --silent --fail --output /dev/null --write-out '%{http_code}' \
            --proto '=https' --proto-redir '=https' \
            --connect-timeout 3 --max-time 10 \
            --retry 1 --retry-delay 1 --retry-max-time 15 \
            --config - 2>/dev/null
)" || exit 1
[[ "$http_status" =~ ^2[0-9]{2}$ ]]
