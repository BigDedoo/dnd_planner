# DnD Planner

DnD Planner is a shared availability calendar for tabletop groups. Players mark dates as `Available`, `Maybe`, or `No`, and the app aggregates the group so promising session dates are easy to find.

The current application is deliberately small:

- a Next.js/TypeScript frontend in `frontend/`;
- a FastAPI backend in `backend/`;
- a SQLite database at `dnd_planner.db` by default;
- isolated PostgreSQL migration and legacy-import tooling that is not used by the application runtime.

Availability currently applies globally across all hardcoded groups containing a player. Phase 1B does not change that behavior, import real data, or switch the runtime.

## WSL development setup

### 1. Put the repository in WSL when possible

For faster dependency installation, file watching, linting, and builds, prefer the WSL filesystem instead of `/mnt/c`:

```bash
mkdir -p ~/src
cd ~/src
git clone https://github.com/BigDedoo/dnd_planner.git
cd dnd_planner
```

The existing Windows-mounted checkout still works, but npm operations can be noticeably slower there.

### 2. Install prerequisites

Use Ubuntu under WSL2 with Python 3.12 and Node.js 22. If `uv` is not installed:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
```

Load Node when it is installed through `nvm`:

```bash
source ~/.nvm/nvm.sh
node --version
npm --version
```

### 3. Create local environment files

From the repository root:

```bash
cp .env.example .env
cp frontend/.env.example frontend/.env.local
```

The committed examples contain development-safe values and no secrets. Local `.env` and `.env.local` files are ignored by Git.

### 4. Install locked dependencies

Backend:

```bash
uv sync --frozen
```

Frontend:

```bash
cd frontend
npm ci
cd ..
```

`uv sync --frozen` uses the committed `uv.lock` without changing it. `npm ci` uses `frontend/package-lock.json`.

## Backend tests

From the repository root:

```bash
uv run pytest
```

The backend tests create a separate temporary SQLite database for every test. They never read from or modify the repository's `dnd_planner.db` file.

The PostgreSQL-specific model and migration tests require the guarded `TEST_DATABASE_ADMIN_URL` described below. They create and remove only a randomly named `dnd_planner_test_*` database.

The source-only importer tests generate their own temporary SQLite fixtures. No importer test selects the repository's application database.

## Quality checks

Run the complete local quality gate from anywhere inside WSL:

```bash
./scripts/check.sh
```

The full gate performs a frozen backend sync and reinstalls frontend dependencies with `npm ci`. For faster day-to-day checks, run the relevant commands individually from the repository root:

```bash
uv run ruff check backend
uv run ruff format --check backend
uv run pytest
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

GitHub Actions runs the same backend and frontend quality gates for pull requests and pushes to the default branch.

Without `TEST_DATABASE_ADMIN_URL`, `scripts/check.sh` prints a warning, runs every Phase 0 check, and explicitly skips the PostgreSQL gate. With the variable set, it also requires every PostgreSQL test to run without skips.

## Phase 1A PostgreSQL tooling

PostgreSQL is currently used only by Alembic and the new-model tests. FastAPI still uses `DATABASE_PATH`, starts without Docker or `DATABASE_URL`, and has no importer or PostgreSQL runtime cutover.

Start the one-service local PostgreSQL instance:

```bash
docker compose -f compose.postgres.yml up -d --wait postgres
docker compose -f compose.postgres.yml ps
docker compose -f compose.postgres.yml logs -f postgres
```

Configure the guarded test administrator and the separate Alembic application target:

```bash
export TEST_DATABASE_ADMIN_URL='postgresql+psycopg://dnd_planner:dnd_planner_local_only@127.0.0.1:5432/postgres'
export DATABASE_URL='postgresql+psycopg://dnd_planner:dnd_planner_local_only@127.0.0.1:5432/dnd_planner'

uv run alembic upgrade head
uv run alembic check
PHASE1A_REQUIRE_POSTGRES=1 uv run pytest -q backend/tests/postgres
./scripts/check.sh
```

The test fixture validates the driver, host, maintenance database, and generated database name before creating or dropping anything. Alembic owns the new schema; application startup never calls `create_all` or runs a migration. Upgrade/downgrade/re-upgrade testing occurs only in guarded disposable `dnd_planner_test_*` databases—never run `alembic downgrade` against `dnd_planner` or real data.

Stop PostgreSQL while retaining the local development volume:

```bash
docker compose -f compose.postgres.yml down
```

The following command permanently deletes the local Compose volume. It is destructive, local-development-only, and must never target real data:

```bash
docker compose -f compose.postgres.yml down --volumes
```

## Phase 1B legacy importer

Phase 1B adds a fail-closed `inspect`, `plan`, `apply`, and `verify` workflow while FastAPI continues using legacy SQLite through `DATABASE_PATH`. Implementation and automated tests are synthetic-only. See [the legacy import runbook](docs/LEGACY_IMPORT_RUNBOOK.md) for the explicit-path, environment-variable, artifact, rollback, and later rehearsal contract. Do not select any real source or destination without separate authorization.

## Start the application

Open two WSL terminals in the repository.

### Terminal 1: FastAPI

```bash
uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2: Next.js

```bash
source ~/.nvm/nvm.sh
cd frontend
npm run dev -- --hostname 0.0.0.0 --port 3000
```

Open [http://localhost:3000](http://localhost:3000) in the Windows browser.

If Windows-to-WSL localhost forwarding is unavailable, get the WSL address:

```bash
hostname -I | awk '{print $1}'
```

Then open `http://<wsl-ip>:3000`, for example `http://172.25.158.215:3000`. The address can change when WSL restarts.

The browser still requests `/api/*` from Next.js. Next.js proxies those requests inside WSL to FastAPI, so the backend can remain bound to `127.0.0.1:8000`.

## Environment variables

### FastAPI: repository-root `.env`

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Valid values: `development`, `test`, `production`. |
| `LOG_LEVEL` | `INFO` | Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `DATABASE_PATH` | `dnd_planner.db` | SQLite file. Relative paths resolve from the repository root. |
| `DATABASE_URL` | local PostgreSQL URL in `.env.example` | Phase 1A Alembic/new-model tooling only; optional for FastAPI and password-redacted by configuration/runtime diagnostics. |
| `CORS_ALLOWED_ORIGINS` | local port 3000 origins | JSON array of exact browser origins; wildcards are rejected. |

FastAPI validates its active values when the application imports. `create_database_runtime()` validates `DATABASE_URL` only when SQLAlchemy/Alembic tooling explicitly requests it. The active application database remains the existing repository-root SQLite file.

### Next.js: `frontend/.env.local`

| Variable | Default | Purpose |
|---|---|---|
| `API_UPSTREAM_URL` | `http://127.0.0.1:8000` | Server-only FastAPI target for the browser-facing `/api/*` rewrite. |

`API_UPSTREAM_URL` must not use a `NEXT_PUBLIC_` prefix because browsers do not need the internal backend address. Restart Next.js after changing it.

## Useful checks

```bash
# Safe backend health response through FastAPI
curl http://127.0.0.1:8000/test-health

# The same response through the Next.js proxy
curl http://127.0.0.1:3000/api/test-health

cd frontend
npm run lint
npm run build
```

## Current product notes

- Clicking a day cycles through `Available -> Maybe -> No -> clear`.
- Right-clicking a day opens a quick status menu.
- Built-in groups, player ordering, and status translations live in `backend/legacy_contract.py` and are consumed by the unchanged SQLite behavior in `backend/database.py`.
- No authentication or authorization exists yet; this phase does not add either.

## Legacy deployment files

`start_app.sh` is a production-style convenience helper. It now uses `uv`, but it still runs `npm run start` and therefore requires `npm run build` first.

`dnd-planner.service` is a clearly marked legacy systemd template. It is not part of the WSL workflow and is not production-ready. Its service user, install location, environment, secrets, and Node/uv paths must be configured before any future deployment. No systemd installation is required for local development.
