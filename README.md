# DnD Planner

DnD Planner is a shared availability calendar for tabletop groups. Players mark dates as `Available`, `Maybe`, or `No`, and the app aggregates the group so promising session dates are easy to find.

The current application is deliberately small:

- a Next.js/TypeScript frontend in `frontend/`;
- a FastAPI backend in `backend/`;
- a SQLite database at `dnd_planner.db` by default.

Availability currently applies globally across all hardcoded groups containing a player. Phase 0A does not change that behavior or the database schema.

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
| `CORS_ALLOWED_ORIGINS` | local port 3000 origins | JSON array of exact browser origins; wildcards are rejected. |

FastAPI validates these values when the application imports. The default database remains the existing repository-root SQLite file.

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
- Built-in groups and player names remain hardcoded in `backend/database.py`.
- No authentication or authorization exists yet; this phase does not add either.

## Legacy deployment files

`start_app.sh` is a production-style convenience helper. It now uses `uv`, but it still runs `npm run start` and therefore requires `npm run build` first.

`dnd-planner.service` is a clearly marked legacy systemd template. It is not part of the WSL workflow and is not production-ready. Its service user, install location, environment, secrets, and Node/uv paths must be configured before any future deployment. No systemd installation is required for local development.
