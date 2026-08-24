# DnD Planner

DnD Planner is a shared availability calendar for tabletop groups. Players mark dates as `Available`, `Maybe`, or `No`, and the app aggregates the group so promising session dates are easy to find.

The current application is deliberately small:

- a Next.js/TypeScript frontend in `frontend/`;
- a FastAPI backend in `backend/`;
- a PostgreSQL application runtime configured through `DATABASE_URL`;
- a retained SQLite implementation used only as the rollback/test oracle;
- isolated Alembic and legacy-import tooling.

Phase 1C-A keeps availability global across all memberships and preserves the existing `/api/*` frontend contract. It does not migrate real data, deploy the application, or perform the final cutover.

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

Legacy tests create a separate temporary SQLite database for every test. They never read from or modify the repository's `dnd_planner.db` file.

PostgreSQL model, importer, and compatibility-runtime tests require the guarded `TEST_DATABASE_ADMIN_URL` described below. They create and remove only randomly named `dnd_planner_test_*` databases provisioned through Alembic.

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

Without `TEST_DATABASE_ADMIN_URL`, `scripts/check.sh` prints a warning, runs every source/legacy check, and explicitly reports that PostgreSQL compatibility is unproven locally. With the variable set, every Phase 1A/1B/1C PostgreSQL test must execute without skips.

## PostgreSQL runtime and guarded test tooling

Normal FastAPI startup now requires `DATABASE_URL`. Startup connects with `SELECT 1`, requires the exact repository Alembic head, and validates the three imported legacy group projections before serving requests. Startup never runs Alembic or creates schema objects.

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
REQUIRE_POSTGRES_TESTS=1 uv run pytest -q backend/tests/postgres
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

The fail-closed `inspect`, `plan`, `apply`, and `verify` workflow remains independent from application settings. It requires explicit source/backup paths and an explicit destination environment-variable name, never falls back to `DATABASE_URL`, and never runs Alembic. Automated use remains synthetic-only. See [the legacy import runbook](docs/LEGACY_IMPORT_RUNBOOK.md).

## Phase 1C-A compatibility runtime

`backend/compatibility.py` implements the temporary name-shaped API over request-scoped SQLAlchemy sessions. The existing routes and response shapes remain available, but invalid statuses and writes targeting an unknown group, unknown user, or nonmember now fail with HTTP 422.

Set `MUTATIONS_ENABLED=false` to start in read-only smoke-test mode. GET routes and `/test-health` continue working, while `POST /availability` returns HTTP 503 before opening a database transaction. The intended future cutover sequence is:

```text
mutations disabled
-> separately migrate/import/verify
-> start the PostgreSQL app
-> perform a read-only smoke test
-> enable mutations
```

Phase 1C-A does not authorize those real-data steps. The five compatibility routes are temporary and scheduled for replacement/removal by scoped Phase 2 APIs.

## Start the application

Open two WSL terminals in the repository.

### Terminal 1: FastAPI

Before startup, configure `DATABASE_URL`, run Alembic separately, and populate an exact verified compatibility dataset. For a future pre-write smoke test, set `MUTATIONS_ENABLED=false`.

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

## Phase 2 authentication and authorization

Phase 2 introduces Clerk authentication, Next.js session management, official Clerk backend request authentication, and internal PostgreSQL account persistence.

### Architecture

```text
Internet
  -> Caddy Basic Auth (retained)
  -> Next.js 16 (App Router + @clerk/nextjs proxy.ts)
  -> /api/* (Proxies requests with Bearer session token)
  -> FastAPI (Official Clerk SDK; session tokens only)
  -> PostgreSQL 17 (accounts + account_identities)
```

### Internal identity model

Authentication identity is separated from the legacy DnD domain identity:

- `accounts`: Internal account identity (`id` UUID PRIMARY KEY) plus optional Clerk-synchronized `email`, `username`, `display_name`, and `profile_synced_at` metadata.
- `account_identities`: Provider link (`id` UUID, `account_id` FK -> `accounts.id`, `provider="clerk"`, `provider_subject` immutable external subject).

The stable internal identity is `accounts.id`. Email, username, and display name are mutable profile metadata, never authentication, authorization, account-merging, or legacy-player matching keys. Profiles are refreshed from Clerk after verification at most once every 24 hours after a successful sync. Migrated legacy DnD users (`users.id`) remain untouched and are not automatically linked.

### Authenticated endpoint

- `GET /api/me` (and `GET /me`): Requires a valid Clerk bearer token. Returns safe internal account info:
  ```json
  {
    "id": "uuid-...",
    "email": "user@example.com",
    "username": "adventurer",
    "display_name": "Adventurer"
  }
  ```
  Unauthenticated or invalid requests receive HTTP 401. First authenticated request idempotently provisions an internal `accounts` and `account_identities` row.

### Intentionally deferred

- Caddy site-wide Basic Auth remains enabled.
- Legacy account claiming is deferred; account-to-user linking remains an explicit operator action.
- Group creation and member invitation links are deferred.
- Billing and Stripe payments are deferred.

### Clerk CLI and linked application

- Linked Clerk application ID: `app_3Hx8Ad1Rops49U59inWXhEl1UCM`
- Check CLI status: `clerk doctor`
- Pull instance variables: `clerk env pull`

## Phase 2B authenticated app, backend hardening, and my groups

Phase 2B uses the official Clerk backend SDK with an explicit session-token-only and authorized-parties policy. The application remains organized around authenticated accounts, explicit DnD user profiles, membership-authorized APIs, and protected Next.js routes.

### Architecture flow

```text
Clerk Session
  -> Account (accounts.id)
  -> Linked DnD User (users.account_id -> accounts.id)
  -> Group Memberships (group_memberships)
  -> Groups (groups.id)
  -> Availability
```

### Key features & routes

- `/`: Landing page for guests with Sign In / Sign Up buttons. Authenticated users are automatically routed to `/app`.
- `/app`: Authenticated dashboard displaying "My Groups" based only on the active user's memberships.
- `/groups/[groupId]`: Authenticated group workspace with live group calendar, group switcher selector in the shell header, and role-based controls.
- `GET /api/me/groups`: Returns only groups the authenticated user belongs to.
- `GET /api/groups/{group_id}`: Returns group details and member roster (403 for non-members).
- `GET /api/groups/{group_id}/availability/{year}/{month}`: Returns monthly group availability (403 for non-members).
- `POST /api/groups/{group_id}/availability`: Updates authenticated user's own availability (prevents user impersonation).
- `GET /api/groups/{group_id}/admin/availability`: Administrative overview available strictly to `MembershipRole.OWNER` (403 for non-owners).
- `GET /api/groups/{group_id}/confirmed-sessions?start=...&end=...`: Returns scheduled sessions to group members; `include_cancelled=true` is used by the group session history.
- `PUT` / `PATCH` / `DELETE /api/groups/{group_id}/confirmed-sessions/{day}`: Creates, edits, or softly cancels a session for owners and organizers.
- `GET /api/me/confirmed-sessions?start=...&end=...`: Returns confirmed sessions from every group belonging to the authenticated DnD user.
- `GET /api/groups/{group_id}/confirmed-sessions/{day}/calendar.ics`: Authenticated individual-session calendar export.
- `GET /api/me/confirmed-sessions.ics`: Authenticated personal upcoming-session calendar export.

Confirmed sessions are informational. They never change a player's availability. The group calendar highlights its own confirmed dates and displays all same-day confirmed sessions from the player's other groups as non-blocking reminders.

Session event and reminder delivery is intentionally local-only for now. The default adapter records deduplicated deliveries and logs IDs only; it does not send email. Preview due reminders safely with:

```bash
uv run python -m backend.cli.process_session_reminders --dry-run --days-ahead 7
```

Omit `--dry-run` to record due deliveries. No cron/systemd timer or external provider is configured in this phase.

### Operator legacy linking tool

To explicitly associate a legacy migrated user (`users` table) with an authenticated account (`accounts` table):

```bash
uv run python -m backend.link_account --account-id <ACCOUNT_UUID> --user-id <USER_UUID>
```

- Add `--dry-run` to preview the link without modifying the database.
- Idempotent and fails safe if either side is already linked to another entity.
- Output includes the account UUID and its synchronized email, username, and display name. Linking remains an explicit UUID-to-UUID operator action; profile fields are never used for automatic matching.

### Intentionally deferred

- Caddy Basic Auth remains enabled during local and staging verification.
- Group creation, invite links/codes, and email invitations are deferred.
- Billing, subscriptions, and Stripe payments are deferred.

## Environment variables

### FastAPI: repository-root `.env`

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Valid values: `development`, `test`, `production`. |
| `LOG_LEVEL` | `INFO` | Valid values: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `DATABASE_URL` | none | Required active PostgreSQL target for normal FastAPI startup and Alembic. Must use `postgresql+psycopg`; diagnostics redact passwords. |
| `MUTATIONS_ENABLED` | `true` | Set `false` for Phase 1C read-only smoke/maintenance mode; POST returns HTTP 503 without a write transaction. |
| `DATABASE_PATH` | `dnd_planner.db` | Legacy SQLite rollback/tests and explicit source tooling only. Relative paths resolve from the repository root. |
| `CORS_ALLOWED_ORIGINS` | local port 3000 origins | JSON array of exact browser origins; wildcards are rejected. |
| `CLERK_SECRET_KEY` | none | Server-only Clerk secret used by the official backend SDK; required in production. |
| `CLERK_AUTHORIZED_PARTIES` | none | Required in production. JSON array of exact HTTP(S) origins passed to Clerk request authentication. |

### Next.js: `frontend/.env.local`

| Variable | Default | Purpose |
|---|---|---|
| `API_UPSTREAM_URL` | `http://127.0.0.1:8000` | Server-only FastAPI target for the browser-facing `/api/*` rewrite. |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | none | Clerk public instance key. |
| `CLERK_SECRET_KEY` | none | Clerk secret key for Next.js server-side operations. |

## Useful checks

```bash
# Backend health response through FastAPI
curl http://127.0.0.1:8000/test-health

# The same response through the Next.js proxy
curl http://127.0.0.1:3000/api/test-health

# Authenticated account check (requires Bearer token)
curl -H "Authorization: Bearer <clerk_token>" http://127.0.0.1:8000/api/me

cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
```

## Legacy deployment files

`start_app.sh` is a production-style convenience helper. It now uses `uv`, but it still runs `npm run start` and therefore requires `npm run build` first.

`dnd-planner.service` is a clearly marked legacy systemd template. It is not part of the WSL workflow and is not production-ready. Its service user, install location, environment, secrets, and Node/uv paths must be configured before any future deployment. No systemd installation is required for local development.
