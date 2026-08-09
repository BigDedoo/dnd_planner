#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

section() {
    printf '\n==> %s\n' "$1"
}

section "Verify Python lockfile"
uv lock --check

section "Synchronize frozen Python environment"
uv sync --frozen

section "Lint backend"
uv run ruff check backend

section "Check backend formatting"
uv run ruff format --check backend

section "Test legacy SQLite backend"
uv run pytest -q --ignore=backend/tests/postgres

if [[ -z "${TEST_DATABASE_ADMIN_URL:-}" ]]; then
    printf '\nWARNING: PostgreSQL-specific Phase 1A tests were skipped.\n'
    printf 'Set TEST_DATABASE_ADMIN_URL and rerun this script; this run does not prove the PostgreSQL gate passed.\n'
else
    section "Test PostgreSQL models and migrations"
    PHASE1A_REQUIRE_POSTGRES=1 uv run pytest -q backend/tests/postgres
fi

section "Install frozen frontend dependencies"
npm --prefix frontend ci --no-audit --no-fund --progress=false

section "Lint frontend"
npm --prefix frontend run lint

section "Type-check frontend"
npm --prefix frontend run typecheck

section "Build frontend"
npm --prefix frontend run build
