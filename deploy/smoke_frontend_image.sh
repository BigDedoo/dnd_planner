#!/usr/bin/env bash
# Public-route packaging smoke: no backend, credentials, or host ports required.
# The production API healthcheck remains enabled and unchanged.
set -Eeuo pipefail

image="${1:?Usage: bash deploy/smoke_frontend_image.sh IMAGE}"
container=""
cleanup() {
    status=$?
    if [[ -n "$container" ]]; then
        if [[ "$status" -ne 0 ]]; then
            docker logs --tail 100 "$container" >&2 || true
        fi
        docker rm --force "$container" >/dev/null
    fi
    exit "$status"
}
trap cleanup EXIT

# Syntactically valid test placeholders, never real Clerk credentials.
container="$(docker run --detach \
    --env NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_c21va2UuY2xlcmsuYWNjb3VudHMuZGV2JA== \
    --env CLERK_SECRET_KEY=sk_test_ci_placeholder \
    "$image")"

docker exec --interactive "$container" node --input-type=module <<'NODE'
import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

const origin = 'http://127.0.0.1:3000';
let response;
for (let attempt = 0; attempt < 60; attempt++) {
    try {
        response = await fetch(`${origin}/terms`, {
            redirect: 'manual', signal: AbortSignal.timeout(2000),
        });
        break;
    } catch {
        await delay(1000);
    }
}
assert.equal(response?.status, 200, '/terms must return 200');
const html = await response.text();
assert.ok(html.includes('Terms of Use'), 'the actual Terms page must render');
const assets = [...new Set([...html.matchAll(/(?:src|href)="(\/_next\/static\/[^"?#]+)[^"]*"/g)]
    .map(match => match[1]))];
assert.ok(assets.some(path => path.endsWith('.js')), 'JavaScript assets must be present');
assert.ok(assets.some(path => path.endsWith('.css')), 'CSS assets must be present');
for (const path of [...assets, '/file.svg']) {
    const asset = await fetch(`${origin}${path}`, { signal: AbortSignal.timeout(5000) });
    assert.equal(asset.status, 200, `${path} must return 200`);
    assert.ok(!asset.headers.get('content-type')?.includes('text/html'), `${path} must be an asset`);
    assert.ok((await asset.arrayBuffer()).byteLength > 0, `${path} must not be empty`);
}
await delay(5000);
assert.equal((await fetch(`${origin}/terms`, { signal: AbortSignal.timeout(5000) })).status, 200);
console.log(`/terms: 200; ${assets.length} static assets + public SVG: 200; server remains reachable`);
NODE

[[ "$(docker inspect --format '{{.State.Running}}|{{.RestartCount}}' "$container")" == "true|0" ]]
printf 'FRONTEND IMAGE RUNTIME SMOKE: PASS\n'
