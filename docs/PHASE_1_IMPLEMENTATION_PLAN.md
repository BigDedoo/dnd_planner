# Phase 1 implementation plan

Status: design only. This document does not authorize an implementation or a migration of real data.

Planning baseline: `master`, after Phases 0A, 0B, and 0C. The repository was inspected from source and tests. The real `dnd_planner.db` was deliberately not opened, queried, copied, or modified. The roadmap's statement that the legacy database currently contains 324 rows is therefore an unverified historical observation, not an input that this plan trusts. Every real-data fact must be rediscovered by the read-only importer dry run.

## Phase 1 objective

Phase 1 introduces a PostgreSQL-ready persistence foundation while retaining the current browser experience and name-shaped API. It is intentionally split so that the repository remains runnable and rollback remains straightforward after every merge:

1. **Phase 1A — SQLAlchemy and migration foundation:** add synchronous SQLAlchemy 2 models, Alembic, PostgreSQL-only local infrastructure, and constraint tests. The running FastAPI application continues using the current SQLite implementation.
2. **Phase 1B — legacy importer:** add a read-only SQLite-to-PostgreSQL importer, deterministic identity mapping, exhaustive validation, verification artifacts, and rehearsal tests. The running FastAPI application still uses SQLite.
3. **Phase 1C — compatibility and cutover:** put the existing endpoints over SQLAlchemy, preserve their current shapes and global availability behavior, run the final import, and switch `DATABASE_URL` only after verification.

Phase 1 does not add authentication, authorization, account claiming, ID-shaped `/v1` endpoints, group management, invitations, subscriptions, sessions, frontend redesign, or a new frontend state framework. Those remain later roadmap phases.

Current startup commands, which must continue to work through 1A and 1B, are:

```bash
# Backend, from the repository root
uv sync --frozen
uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# Frontend, from frontend/
npm ci
npm run dev -- --hostname 0.0.0.0 --port 3000
```

The Windows-accessible URL remains `http://localhost:3000`; the browser continues to call `/api/*`, and Next.js continues to proxy those calls to the server-only `API_UPSTREAM_URL`.

## Current behavior to preserve

The source and regression tests establish the following contract.

### Current data and startup contract

- `backend/config.py` reads `APP_ENV`, `LOG_LEVEL`, `DATABASE_PATH`, and `CORS_ALLOWED_ORIGINS`. `DATABASE_PATH` resolves relative paths from the repository root.
- The default store is SQLite at `dnd_planner.db`. The Phase 0 app factory initializes its configured SQLite schema in the FastAPI lifespan; importing `backend.main` alone does not create the schema. The roadmap's older statement about import-time schema creation is no longer current.
- `backend/tests/conftest.py` gives every test its own temporary SQLite file and enters `TestClient` as a context manager so lifespan behavior runs. `test_app_factory.py` proves two app instances can use different database paths without leaking settings.
- `GET /test-health` returns exactly `{"status":"ok"}` and does not reveal a file path or infrastructure detail.
- The production application has no authentication or authorization. The profile selector permits acting as any hardcoded profile; Phase 1 must not pretend to solve this.

### Current groups and memberships

`backend/database.py` contains three groups in this observable order, with players in the following observable order:

| Group | Players |
|---|---|
| `Green flag` | `Quentin`, `Arnaud`, `Ulrich`, `Daerrus`, `Dembe` |
| `1D6` | `Gaelle`, `Rico`, `Yoann`, `Romane`, `Victor`, `Dembe` |
| `Underdark` | `Dembe`, `Arnaud`, `Quentin`, `Martin`, `Baptiste` |

There are twelve distinct exact, case-sensitive profile names. `Dembe`, `Arnaud`, and `Quentin` demonstrate cross-group membership. Names are mutable identifiers in the old design; no normalization, case folding, or fuzzy matching is performed.

`GET /groups` returns an array of objects shaped as `{"name": string, "players": string[]}`. The compatibility implementation must return the three imported groups and preserve the order above. New group management is not part of Phase 1.

### Current availability persistence

The SQLite table has only these columns:

```text
availability(group_name TEXT, user_name TEXT, date TEXT, status TEXT)
PRIMARY KEY (group_name, user_name, date)
```

It has no foreign keys, `NOT NULL` constraints, status constraint, or timestamps.

Despite that physical group-scoped key, the product rule is **global availability per exact user name and date**:

- A write for a known player is copied to the supplied group plus every hardcoded group containing that player.
- A truthy status uses replacement semantics. A false/`null` status deletes that user's date from every one of their groups.
- Reads expand older or incomplete rows across all hardcoded memberships. If a source row for the requested target group exists, that target-specific row wins during expansion.
- The existing frontend also fans one logical update out to all the user's groups. The backend therefore receives redundant writes; they are expected to remain harmless through Phase 1C.
- Conflicting legacy statuses for the same user/date cannot be represented by the new global model. The importer must report every conflicting source row and stop; it must never guess precedence.

### Current endpoint contract

| Endpoint | Current behavior that Phase 1C must preserve |
|---|---|
| `GET /groups` | Returns current name-shaped groups and player arrays. |
| `GET /availability/{group}/{year}/{month}` | Returns rows shaped as `group_name`, `user_name`, `date`, `status`; includes only members of the exact group and dates in the requested month; shared-user availability appears in every group; an unknown group returns `200 []`. |
| `POST /availability` | Accepts `group`, `user`, ISO date, and nullable string `status`; canonical UI writes return `{"status":"success","new_state":<input status>}`; `null` clears the date globally. Date parse failures are FastAPI `422` responses. |
| `GET /admin/all-availability?start=...&end=...` | The date range is inclusive at both ends. Rows are expanded to all memberships, so one global fact can appear once per group. It remains anonymous in Phase 1. |
| `GET /test-health` | Returns exactly `{"status":"ok"}`. |

Exact wire shapes are:

```text
GroupInfo = {"name": string, "players": string[]}
AvailabilityUpdate = {"group": string, "user": string, "date": "YYYY-MM-DD", "status": string | null}
AvailabilityRow = {"group_name": string, "user_name": string, "date": "YYYY-MM-DD", "status": string}
WriteResponse = {"status": "success", "new_state": string | null}
HealthResponse = {"status": "ok"}
```

`GET /groups` returns `GroupInfo[]`; both availability reads return `AvailabilityRow[]`. The path `year` and `month` are parsed as integers; `start`, `end`, and write `date` are parsed as dates by FastAPI/Pydantic. The tests assert the detailed Pydantic `422` location/type/input for a malformed write date, so Phase 1C must retain that validation response.

The regression suite currently contains a strict expected failure documenting that arbitrary status strings are accepted. Phase 1A and 1B must leave that test unchanged. Phase 1C needs an explicit operator decision because the required normalized status constraint makes arbitrary values unrepresentable; this is a blocking compatibility exception, not an incidental cleanup. If that change is approved, Phase 1C should reject noncanonical status values with `422` and convert the strict xfail into a passing test. If it is not approved, the write cutover must not proceed.

Likewise, the relational target cannot faithfully persist a write naming an unknown group, unknown profile, or nonmember, even though the unconstrained legacy function can create such an invisible SQLite row. The current UI never emits those writes and the regression suite does not depend on them. Phase 1C should reject them with a documented `422` only after explicit approval; returning success while dropping data is not acceptable.

### Current frontend contract

- `frontend/src/services/api.ts` uses browser-relative `/api` URLs and calls the five compatibility routes above.
- `frontend/next.config.ts` rewrites `/api/:path*` to the server-only `API_UPSTREAM_URL`, defaulting to `http://127.0.0.1:8000`. No `NEXT_PUBLIC_` backend URL is needed.
- `frontend/src/app/page.tsx` performs optimistic updates across every group containing the selected profile.
- A normal click cycles status in the exact sequence documented below. The quick menu sends the same three exact strings or `null`.
- Calendar aggregation treats only exact `Available` as available, sometimes includes `Maybe` for a guest calculation, and treats no row as pending/not set.
- Phase 1 should require no frontend product code changes. Any frontend edit during implementation must be justified as a compatibility correction and separately approved.

## Status mapping

The new database stores stable lowercase domain values. The temporary compatibility layer is the only place that translates those values to and from the current API strings.

| Frontend cycle | Frontend display label | Frontend value sent | Backend request value | Legacy SQLite value | Regression-test value/expectation | New database value | Importer mapping |
|---:|---|---|---|---|---|---|---|
| 1 | `Available` | `"Available"` | `"Available"` | `"Available"` | sends/reads exact `Available`; row is shared across groups | `available` | exact `Available` maps to `available` |
| 2 | `Maybe` | `"Maybe"` | `"Maybe"` | `"Maybe"` | sends/reads exact `Maybe`; row replaces prior value globally | `maybe` | exact `Maybe` maps to `maybe` |
| 3 | Quick/detail views use `No`; some summary and accessibility text says `Unavailable` | `"No"` | `"No"` | `"No"` | sends/reads exact `No`; row replaces prior value globally | `unavailable` | exact `No` maps to `unavailable` |
| 4 | Clear / `Not set` / `Pending` | `null` | Python `None` after Pydantic parsing | no row after delete | sends `null`; prior row is absent in every group | no row | no source row is created; a stored SQL `NULL`/empty value is invalid input and fails import |

The discrepancy is therefore resolved as follows: **`Unavailable` is display copy, not an API or legacy persistence value.** The actual cycle is `Available → Maybe → No → null`. The importer must use an explicit, closed mapping of the three exact legacy strings. It must fail on different casing, leading/trailing whitespace, `Unavailable`, empty strings, SQL `NULL`, or any other value and include row coordinates in its report.

## Recommended architecture

Keep the current shallow `backend/` package. Do not create the future `backend/app/` hierarchy merely to match the roadmap diagram.

```text
backend/
  config.py                         # add DATABASE_URL; retain DATABASE_PATH
  database.py                       # frozen legacy SQLite implementation through cutover
  db.py                             # engine/session runtime, no global configured engine
  models.py                         # four SQLAlchemy models and domain enums
  group_service.py                  # exactly-one-owner transaction rules
  legacy_contract.py                # immutable current names/order/status mapping
  compatibility.py                 # Phase 1C name-shaped SQLAlchemy queries
  main.py                           # existing app and routes; switch only in 1C
  cli/
    __init__.py
    import_legacy_sqlite.py
  migrations/
    env.py
    script.py.mako
    versions/
      0001_phase_1_domain_schema.py
  tests/
    ...existing tests...
    postgres/
      conftest.py
      test_models.py
      test_group_service.py
      test_migrations.py
      test_compatibility_api.py
    test_import_legacy_sqlite.py
alembic.ini
compose.postgres.yml
```

### Runtime and configuration decisions

- Use synchronous SQLAlchemy 2 and Psycopg 3. The current traffic and synchronous domain operations do not justify an async database stack.
- Add runtime dependencies only: `sqlalchemy>=2.0,<2.1`, `alembic>=1.18,<2`, and `psycopg[binary]>=3.2,<4`. Resolve and commit them with `uv`; do not upgrade unrelated packages. Do not add SQLModel, asyncpg, a repository framework, Docker SDK, or a CLI framework—the importer can use `argparse`.
- Add `DATABASE_URL` to `Settings` as optional in 1A/1B because the running application still uses SQLite. Use an explicit local value in `.env.example`: `postgresql+psycopg://dnd_planner:dnd_planner_local_only@127.0.0.1:5432/dnd_planner`.
- Retain `DATABASE_PATH` for the legacy runtime through 1B and for isolated legacy tests/import source handling after 1C. Never reinterpret it as a SQLAlchemy URL.
- In 1C, `DATABASE_URL` becomes required for the runtime application. Validate it with SQLAlchemy's URL parser, require the `postgresql+psycopg` driver, and redact passwords from every message and report.
- `create_database_runtime(database_url)` returns one small object containing an `Engine` and `sessionmaker`. It must not run DDL. Recommended engine settings are `pool_pre_ping=True` and otherwise conservative SQLAlchemy defaults until hosted limits are known.
- Do not create an engine or sessionmaker at module import. `create_app(settings, database_runtime=None)` constructs or accepts an isolated runtime, stores it on `app.state`, and disposes its engine in lifespan shutdown. This preserves the app-factory isolation already tested in Phase 0B.
- A FastAPI dependency obtains the runtime from `request.app.state`, opens one `Session` per request, yields it, rolls back on exception, and always closes it. Service functions own transaction boundaries for writes.
- `compatibility.py` contains concrete query functions for the five temporary routes. It is not a generic repository interface. `group_service.py` exists only because the exactly-one-owner rule spans multiple writes; straightforward compatibility reads/writes use SQLAlchemy directly.
- Do not call `Base.metadata.create_all()` in application code, tests, importer, or scripts. Every database used by the new model must reach the required revision through Alembic.
- Do not run Alembic automatically at FastAPI startup. Startup may perform a read-only connectivity/revision check and fail with a redacted, actionable message when the database is unreachable or not at head.

The [SQLAlchemy UUID documentation](https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.Uuid) supports a backend-neutral `Uuid` that becomes native PostgreSQL `UUID` and an emulated `CHAR(32)` on backends without UUID support. The [Psycopg dialect documentation](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg) defines the synchronous URL as `postgresql+psycopg://...`. These choices retain type portability for metadata-level tests while making PostgreSQL the authoritative new runtime.

### Responsibility boundary by subphase

| Component | 1A | 1B | 1C |
|---|---|---|---|
| Existing SQLite routes | active and unchanged | active and unchanged | retained only as rollback/test code |
| SQLAlchemy models/Alembic | added and tested | unchanged except importer needs | active runtime schema |
| Importer | absent | added; target only | used for final cutover/verification |
| PostgreSQL | disposable schema/model tests | disposable import rehearsals | application runtime |
| Existing frontend | unchanged | unchanged | unchanged |

## Exact model specification

Only four domain models belong in the initial revision: `User`, `Group`, `GroupMembership`, and `Availability`. Authentication records, invitations, sessions, responses, subscriptions, claims, and audit tables are explicitly excluded.

### Shared type and timestamp rules

- IDs are Python `uuid.UUID` values mapped with `sqlalchemy.Uuid(as_uuid=True, native_uuid=True)`. PostgreSQL gets native `UUID`; SQLite type compilation, where used only for tooling, gets `CHAR(32)`.
- Normal application-created IDs use UUIDv4 generated in Python (`default=uuid.uuid4`). Do not add a PostgreSQL UUID extension or server-side generator in this phase.
- Every constraint and index has a stable explicit name so Alembic diffs and error handling are predictable.
- Persist timestamps as `TIMESTAMP WITH TIME ZONE` using `DateTime(timezone=True)`, with `server_default=func.now()`. Treat values as UTC at application boundaries.
- `updated_at` also has SQLAlchemy `onupdate=func.now()`. PostgreSQL has no generic column-level `ON UPDATE`; therefore every bulk/Core update must explicitly set `updated_at`. Do not add a trigger in Phase 1.
- Use Python `StrEnum` values plus `VARCHAR` columns and explicit `CHECK` constraints. Do not create native PostgreSQL enum types in Phase 1.

Native PostgreSQL enums offer database-level typing but make adding/removing/renaming values and downgrades more operationally involved. Check-constrained strings still reject invalid values, work consistently in PostgreSQL and test tooling, and can be changed in a normal reviewed migration. The exact values are:

```text
MembershipRole: owner | organizer | member
AvailabilityStatus: available | maybe | unavailable
```

SQLAlchemy enum mappings must use the enum **values**, not Python member names, validate strings, compile to bounded `VARCHAR`, and rely on explicitly named checks in the migration. Migration scripts must spell out the values rather than importing live model constants.

### `users`

| Column | SQLAlchemy/PostgreSQL type | Python type | Null/default | Constraints and purpose |
|---|---|---|---|---|
| `id` | `Uuid` / native `UUID` | `uuid.UUID` | non-null; Python UUIDv4 default | primary key `pk_users` |
| `auth_provider` | `String(50)` / `VARCHAR(50)` | `str \| None` | nullable | both auth fields remain null for unclaimed imports |
| `auth_subject` | `String(255)` / `VARCHAR(255)` | `str \| None` | nullable | provider-specific stable subject, never the application PK |
| `email` | `String(320)` / `VARCHAR(320)` | `str \| None` | nullable | imported profiles may be unclaimed and have no email |
| `display_name` | `String(120)` / `VARCHAR(120)` | `str` | non-null | mutable and intentionally not globally unique |
| `timezone` | `String(64)` / `VARCHAR(64)` | `str` | non-null; Python/server default `UTC` | application validates an IANA timezone when accounts are introduced |
| `created_at` | `DateTime(timezone=True)` / `TIMESTAMPTZ` | aware `datetime` | non-null; server `now()` | creation audit time |
| `updated_at` | `DateTime(timezone=True)` / `TIMESTAMPTZ` | aware `datetime` | non-null; server `now()`; application on-update | last application mutation |

Constraints/indexes:

- `ck_users_display_name_not_blank`: `btrim(display_name) <> ''`.
- `ck_users_auth_identity_pair`: both `auth_provider` and `auth_subject` are null, or both are non-null and nonblank.
- `uq_users_auth_identity`: unique `(auth_provider, auth_subject)`. PostgreSQL permits multiple all-null imported identities; the pair check prevents half-identities.
- `uq_users_email_normalized`: unique index on `lower(email)` where `email IS NOT NULL`. Application writes normalize with Unicode-aware trim plus lowercase before persistence; the database index is the final case-insensitive collision guard.
- `ck_users_email_not_blank`: `email IS NULL OR btrim(email) <> ''`.
- `ck_users_timezone_not_blank`: `btrim(timezone) <> ''`.
- `ix_users_display_name`: nonunique index for the temporary exact-name compatibility lookup. Duplicate display names remain legal; compatibility code must detect ambiguity rather than choose one.

Do **not** add `is_active`, `archived_at`, or soft-delete behavior in Phase 1. No account lifecycle exists yet, and inventing one would create undefined membership and email-reuse semantics. Hard deletion of a user with memberships is restricted as described below. Account deactivation/archival belongs with authenticated account management in Phase 3 or group lifecycle in Phase 4. Until then, nullable email uniqueness conservatively reserves a claimed email.

Relationships:

- `User.memberships` ↔ `GroupMembership.user`, using `back_populates` and `passive_deletes=True`, with no ORM delete-orphan cascade from the user side; the database restricts user deletion while memberships exist.
- `User.availability_entries` ↔ `Availability.user`, using `back_populates`, `cascade="all, delete-orphan"`, and `passive_deletes=True`; the database cascades availability on an explicitly authorized hard delete.

### `groups`

| Column | SQLAlchemy/PostgreSQL type | Python type | Null/default | Constraints and purpose |
|---|---|---|---|---|
| `id` | `Uuid` / native `UUID` | `uuid.UUID` | non-null; Python UUIDv4 default | primary key `pk_groups` |
| `name` | `String(120)` / `VARCHAR(120)` | `str` | non-null | mutable display name; not globally unique in the future SaaS |
| `timezone` | `String(64)` / `VARCHAR(64)` | `str` | non-null; Python/server default `UTC` | IANA timezone for date interpretation |
| `description` | `Text` / `TEXT` | `str \| None` | nullable | optional plain text; importer uses null |
| `created_at` | `DateTime(timezone=True)` / `TIMESTAMPTZ` | aware `datetime` | non-null; server `now()` | creation audit time |
| `updated_at` | `DateTime(timezone=True)` / `TIMESTAMPTZ` | aware `datetime` | non-null; server `now()`; application on-update | last application mutation |

Constraints/indexes:

- `ck_groups_name_not_blank`: `btrim(name) <> ''`.
- `ck_groups_timezone_not_blank`: `btrim(timezone) <> ''`.
- `ix_groups_name`: nonunique index supporting the temporary exact-name adapter.

Group names must not be globally unique because future users can independently create groups with the same display name. During Phase 1C the imported dataset is expected to contain only the three exact legacy names. The compatibility adapter must require one exact match and fail loudly if duplicate names make the old name-shaped route ambiguous. ID-shaped scoped routes in Phase 2 remove this temporary limitation.

Relationship: `Group.memberships` ↔ `GroupMembership.group` uses `back_populates`, `cascade="all, delete-orphan"`, and `passive_deletes=True`; explicit group deletion cascades memberships. Global availability is not deleted with a group.

### `group_memberships`

| Column | SQLAlchemy/PostgreSQL type | Python type | Null/default | Constraints and purpose |
|---|---|---|---|---|
| `group_id` | `Uuid` / native `UUID` | `uuid.UUID` | non-null | FK to `groups.id` with `ON DELETE CASCADE` |
| `user_id` | `Uuid` / native `UUID` | `uuid.UUID` | non-null | FK to `users.id` with `ON DELETE RESTRICT` |
| `role` | `String(16)` / `VARCHAR(16)` backed by `MembershipRole` | `MembershipRole` | non-null; no implicit role for importer | check to `owner`, `organizer`, `member` |
| `display_order` | `Integer` / `INTEGER` | `int` | non-null | preserves current player ordering and supports stable future member lists |
| `joined_at` | `DateTime(timezone=True)` / `TIMESTAMPTZ` | aware `datetime` | non-null; server `now()` | membership creation/import time |

Constraints/indexes:

- Composite primary key `pk_group_memberships` on `(group_id, user_id)`; do not add a surrogate ID.
- `ck_group_memberships_role`: `role IN ('owner','organizer','member')`.
- `ck_group_memberships_display_order`: `display_order >= 0`.
- `uq_group_memberships_display_order`: unique `(group_id, display_order)`.
- `ix_group_memberships_user_id`: index on `user_id` for “my groups” and global projection queries.
- `ix_group_memberships_group_role`: index on `(group_id, role)` for role checks.
- `uq_group_memberships_one_owner`: PostgreSQL partial unique index on `group_id WHERE role = 'owner'`. This guarantees **at most** one owner.

`GroupMembership.group` and `.user` are scalar `back_populates` relationships. A membership has no lifecycle independent of its composite `(group_id, user_id)` identity.

Exactly one owner requires a database constraint plus transaction rules:

- **Creation:** insert the group and its owner membership in one transaction. There is no public group-creation endpoint in Phase 1, but the service invariant and importer use this operation.
- **Transfer:** lock the group row with `SELECT ... FOR UPDATE`; verify the acting/current owner and target membership; update old and new roles atomically using one `CASE` update (or demote then promote within the same transaction); verify one owner before commit. Any error rolls back both changes.
- **Owner leave/removal:** lock the group and reject removal of the owner unless ownership is transferred in the same transaction. A nonowner may be removed normally.
- **Group deletion:** an explicitly authorized whole-group deletion may cascade every membership; “exactly one owner” ceases to apply because the group no longer exists.
- **Direct writes:** route/import code must call the small group service. The partial index is a last-line at-most-one guard; a test must prove the service never commits zero owners.

### `availability`

| Column | SQLAlchemy/PostgreSQL type | Python type | Null/default | Constraints and purpose |
|---|---|---|---|---|
| `user_id` | `Uuid` / native `UUID` | `uuid.UUID` | non-null | FK to `users.id` with `ON DELETE CASCADE` |
| `day` | `Date` / `DATE` | `date` | non-null | date-only fact; no timezone conversion or timestamp |
| `status` | `String(16)` / `VARCHAR(16)` backed by `AvailabilityStatus` | `AvailabilityStatus` | non-null | normalized status check |
| `updated_at` | `DateTime(timezone=True)` / `TIMESTAMPTZ` | aware `datetime` | non-null; server `now()`; application on-update | latest status mutation |

Constraints/indexes:

- Composite primary key `pk_availability` on `(user_id, day)`; no surrogate ID and no `group_id`.
- `ck_availability_status`: `status IN ('available','maybe','unavailable')`.
- `ix_availability_day_user_id`: index on `(day, user_id)` for inclusive admin/date-range scans. The primary key already serves user/date lookups; do not duplicate it.

`Availability.user` is the scalar inverse of `User.availability_entries`; deleting an individual availability object removes only that user's one day.

No row means pending/not answered. Clearing deletes the row. A group calendar is derived by joining memberships to global availability. Group-specific overrides are explicitly deferred until usage demonstrates the need.

## Alembic migration design

### Environment

- Root `alembic.ini` points `script_location` to `backend/migrations` but contains no real credentials.
- `backend/migrations/env.py` imports `Base.metadata`, constructs the URL from typed `DATABASE_URL`, enables `compare_type=True`, and applies the repository naming convention. It must redact URLs in errors/logging.
- Online migration mode is authoritative. Offline SQL generation may be supported for review, but it does not replace execution against disposable PostgreSQL.
- Migration files import only Alembic and SQLAlchemy types. They must not import current model enums or settings whose future changes could alter historical migrations.
- Autogenerate may create a candidate, but the initial migration is manually reviewed and corrected. In particular, checks and PostgreSQL partial indexes must be explicit because [Alembic documents that autogenerate candidates require manual review and do not reliably detect every check constraint](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect).

### Initial upgrade order

`0001_phase_1_domain_schema.py` has one revision and no data migration:

1. Create `users` with primary key and checks.
2. Create user identity/email/display-name indexes.
3. Create `groups` with primary key and checks.
4. Create the group-name index.
5. Create `group_memberships` with both foreign keys, composite primary key, role/order checks, and order uniqueness.
6. Create the membership lookup indexes and PostgreSQL partial unique owner index using `postgresql_where=sa.text("role = 'owner'")`.
7. Create `availability` with its user foreign key, composite primary key, and status check.
8. Create the `(day, user_id)` index.

No seed data belongs in the schema migration. The importer is the only owner-aware legacy data loader.

### Downgrade order

The downgrade is supported for disposable/rehearsal databases and removes objects in dependency order:

1. Drop the availability date index and `availability` table.
2. Drop membership indexes, including the owner partial index, then `group_memberships`.
3. Drop group indexes and `groups`.
4. Drop user indexes and `users`.

Never run this downgrade against a database containing accepted production writes as a rollback technique; it destroys the target schema. Runtime rollback uses the preserved SQLite backup and previous application release.

### Migration tests

- Upgrade a newly created, uniquely named disposable PostgreSQL database from `base` to `head`; inspect every table, type, nullability, PK, FK action, check, unique constraint, and index by exact name.
- Run `alembic check` at head and require no candidate operations.
- Downgrade the same disposable database from `head` to `base`, assert all four domain tables and the version table are gone as expected, then upgrade to `head` again.
- Run a transaction smoke test after re-upgrade.
- Verify module import and FastAPI startup do not create any new SQLAlchemy tables.
- Never use the real or default `dnd_planner.db` in these tests.

## PostgreSQL local-development design

Add one root file, `compose.postgres.yml`, with one service and one named volume. Do not containerize FastAPI or Next.js.

Recommended contract:

| Item | Decision |
|---|---|
| Service name | `postgres` |
| Image | `postgres:17-bookworm` |
| Database | `dnd_planner` |
| User | `dnd_planner` |
| Local-only password | `dnd_planner_local_only` |
| Host binding | `127.0.0.1:5432:5432` |
| Named volume | `dnd_planner_pgdata:/var/lib/postgresql/data` |
| Health check | `pg_isready -U dnd_planner -d dnd_planner`, 5-second interval/timeout, 10 retries |
| Restart policy | none; developer-controlled |

PostgreSQL 17 is recommended rather than `latest`: the [PostgreSQL versioning policy](https://www.postgresql.org/support/versioning/) lists support through November 2029, and a fixed major avoids an accidental major-version data-directory change. The major tag receives compatible minor security/bug fixes; record the resolved image digest in release evidence if exact supply-chain reproducibility is required. Mounting `/var/lib/postgresql/data` is the correct persistence point for PostgreSQL 17 and below according to the [official PostgreSQL image documentation](https://hub.docker.com/_/postgres).

The literal password is acceptable only because the service binds to loopback and is explicitly local development. It must never be reused for hosted environments or copied into a production environment file.

### Local commands

```bash
# Start and wait for health
docker compose -f compose.postgres.yml up -d --wait postgres
docker compose -f compose.postgres.yml ps

# Follow logs when diagnosing startup
docker compose -f compose.postgres.yml logs -f postgres

# Stop while retaining data
docker compose -f compose.postgres.yml down

# Explicit destructive local reset; never use for a real target
docker compose -f compose.postgres.yml down --volumes
```

PostgreSQL tests must never reset the developer database. A session fixture connects through a separately named `TEST_DATABASE_ADMIN_URL` to the local `postgres` maintenance database, verifies that the host is loopback or a known CI service, creates a random database named `dnd_planner_test_<uuid>`, runs Alembic, and drops only that exact generated database in teardown. The cleanup routine rejects names without the exact `dnd_planner_test_` prefix. This supports disposable PostgreSQL while leaving `dnd_planner` intact.

## Phase 1A implementation plan

### Goal

Add and prove the new schema/migration foundation without changing which database serves any existing endpoint.

### Exact file scope

| Action | File | Reason |
|---|---|---|
| Modify | `pyproject.toml` | add SQLAlchemy, Alembic, and Psycopg runtime ranges only |
| Modify | `uv.lock` | lock the added dependency graph |
| Modify | `backend/config.py` | add optional validated `DATABASE_URL` while retaining `DATABASE_PATH` |
| Add | `backend/db.py` | isolated sync engine/session runtime and request-session helper primitives |
| Add | `backend/models.py` | four typed declarative models, enums, naming convention, relationships |
| Add | `backend/group_service.py` | transactional exactly-one-owner operations |
| Add | `alembic.ini` | credential-free Alembic entry point |
| Add | `backend/migrations/env.py` | metadata/URL migration configuration |
| Add | `backend/migrations/script.py.mako` | revision template |
| Add | `backend/migrations/versions/0001_phase_1_domain_schema.py` | empty-target domain schema |
| Add | `compose.postgres.yml` | PostgreSQL-only local service |
| Add | `backend/tests/postgres/conftest.py` | guarded disposable PostgreSQL database fixture |
| Add | `backend/tests/postgres/test_models.py` | constraints, relationships, timestamps, and indexes |
| Add | `backend/tests/postgres/test_group_service.py` | owner invariant transactions |
| Add | `backend/tests/postgres/test_migrations.py` | upgrade/downgrade/re-upgrade and metadata parity |
| Modify | `.env.example` | document `DATABASE_URL` and distinguish it from legacy `DATABASE_PATH` |
| Modify | `README.md` | document PostgreSQL start/stop, migrations, and unchanged SQLite runtime |
| Modify | `.github/workflows/ci.yml` | add PostgreSQL 17 service and migration/model tests to backend job |
| Modify | `scripts/check.sh` | run the migration/model test group when guarded test PostgreSQL is configured; retain all existing checks |

Do not modify `backend/main.py`, `backend/database.py`, any frontend source, existing API expectations, or `dnd_planner.db` in 1A.

### Dependencies

Add only `sqlalchemy>=2.0,<2.1`, `alembic>=1.18,<2`, and `psycopg[binary]>=3.2,<4` as runtime dependencies, then commit the resulting `uv.lock` in the later implementation. Docker Compose supplies PostgreSQL but is not a Python dependency. Existing FastAPI, Pydantic, pytest, Ruff, frontend, and action versions remain unchanged unless the lock solver proves a direct incompatibility and the operator separately approves it.

### Implementation sequence

1. Add the three dependency ranges with `uv`; inspect the resulting lock diff and reject unrelated direct dependency upgrades.
2. Extend typed settings with optional `DATABASE_URL`. Ensure rendering errors hide passwords.
3. Define models and stable naming conventions exactly as specified above.
4. Implement runtime construction without a module-global configured engine and without DDL.
5. Implement and unit-test owner creation/transfer/removal transaction rules.
6. Configure Alembic and hand-review the initial empty-schema migration.
7. Add minimal PostgreSQL Compose and guarded disposable-database fixtures.
8. Add migration and model tests, including exact PostgreSQL catalog checks.
9. Add CI PostgreSQL service and documentation.
10. Re-run the full existing SQLite/API/frontend gate to prove runtime behavior did not change.

### Tests

Retain every existing temporary-SQLite database and TestClient regression. Add direct-session PostgreSQL tests for types, defaults, constraints, FK actions, relationships, owner transactions, and global availability uniqueness. Add Alembic CLI/API tests for base→head, catalog inspection, head equality, check, downgrade, and re-upgrade. Explicitly test that module import and FastAPI startup create no new-schema objects.

### Commands and expected results

```bash
uv add 'sqlalchemy>=2.0,<2.1' 'alembic>=1.18,<2' 'psycopg[binary]>=3.2,<4'
uv lock --check
uv sync --frozen

docker compose -f compose.postgres.yml up -d --wait postgres
export TEST_DATABASE_ADMIN_URL='postgresql+psycopg://dnd_planner:dnd_planner_local_only@127.0.0.1:5432/postgres'
uv run pytest -q backend/tests/postgres

# Against a disposable test URL only
uv run alembic upgrade head
uv run alembic check
uv run alembic downgrade base
uv run alembic upgrade head

uv run ruff check backend
uv run ruff format --check backend
uv run pytest -q
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

Expected: all existing tests remain green with the strict invalid-status xfail still strict; PostgreSQL constraint and migration tests pass; FastAPI still reads/writes its configured SQLite path; `git diff -- dnd_planner.db` is empty.

### CI requirements

- Add a `postgres:17-bookworm` service to the backend job with local-only CI credentials and `pg_isready` health options.
- Supply `TEST_DATABASE_ADMIN_URL` only to PostgreSQL tests. Do not set runtime `DATABASE_URL` for the existing API tests in 1A.
- Keep `uv lock --check`, frozen sync, Ruff, all pytest tests, frontend lint/typecheck/build, branch `master`, least-privilege permissions, and concurrency behavior.
- Increase the backend timeout only if measured migration startup requires it; do not mask hangs with a large timeout.

### Migration considerations

The initial revision targets an empty PostgreSQL database and contains schema only. It must neither read legacy SQLite nor seed users/groups. PostgreSQL catalog tests—not SQLite—are the evidence for UUID compilation, foreign-key actions, checks, and the partial owner index. Because the running API remains on SQLite, applying or reverting this revision on a disposable PostgreSQL target cannot change user-facing behavior.

### Rollback

The runtime is untouched, so rollback is removal/reversion of the 1A files. Stop Compose without deleting its volume unless a disposable reset is intended. Downgrade only disposable databases. No SQLite restoration is needed because 1A never accesses the real SQLite file.

### Definition of done

- A clean checkout can start PostgreSQL, migrate a disposable database, and pass model/migration tests.
- Every required constraint and index is demonstrated on PostgreSQL.
- Existing FastAPI endpoints still use SQLite and all Phase 0 regression tests pass unchanged.
- No schema is created on Python import or FastAPI startup.
- No real data has been inspected or migrated.

### Explicit exclusions

No importer, runtime cutover, dual writes, compatibility SQLAlchemy queries, real-data access, `/v1`, auth, group CRUD, frontend changes, deployment, or hosted database.

## Phase 1B importer design

### Goal

Build and rehearse a deterministic, read-only-source, all-or-nothing importer into an already migrated empty PostgreSQL destination. Do not switch the application runtime.

### Exact file scope

| Action | File | Reason |
|---|---|---|
| Add | `backend/legacy_contract.py` | immutable exact group/player ordering plus status maps used by legacy runtime, importer, and adapter |
| Modify | `backend/database.py` | import the same `GROUPS` value from `legacy_contract.py`; no persistence behavior change |
| Add | `backend/cli/__init__.py` | CLI package marker |
| Add | `backend/cli/import_legacy_sqlite.py` | inspect/dry-run/apply/verify implementation using stdlib `argparse` |
| Add | `backend/tests/test_import_legacy_sqlite.py` | generated temporary SQLite fixtures and report/error tests |
| Add | `backend/tests/postgres/test_import_legacy_sqlite.py` | transactional apply, rerun, verification, and rollback tests |
| Add | `docs/LEGACY_IMPORT_RUNBOOK.md` | exact rehearsal/final commands, artifact retention, troubleshooting |
| Modify | `README.md` | link the runbook; state runtime still uses SQLite |
| Modify | `.gitignore` | ignore local import reports, owner maps, mappings, backups, and database copies by narrow patterns/directories |
| Modify | `.github/workflows/ci.yml` | execute importer dry-run/apply tests against generated fixtures |
| Modify | `scripts/check.sh` | include importer tests in the existing backend pytest gate |

`pyproject.toml` and `uv.lock` should not change in 1B unless implementation proves a missing requirement; the importer intentionally uses the standard library, SQLAlchemy, and Psycopg already added in 1A.

### Dependencies

No new dependency is planned. Use `argparse`, `sqlite3`, `hashlib`, `json`, `pathlib`, `uuid`, `unicodedata`, and atomic filesystem operations from the Python standard library plus the Phase 1A SQLAlchemy/Psycopg stack. If implementation proposes another package, stop for review rather than widening the lockfile automatically.

### CLI contract

Use one module with explicit `inspect`, `plan`, `apply`, and `verify` subcommands and no path defaults. `plan` is the dry run; `apply` consumes the exact approved plan rather than silently recalculating it at a later time:

```bash
uv run python -m backend.cli.import_legacy_sqlite inspect \
  --source-sqlite /absolute/path/to/source.db \
  --report-output /absolute/path/to/inspect-report.json

uv run python -m backend.cli.import_legacy_sqlite plan \
  --source-sqlite /absolute/path/to/source.db \
  --backup-sqlite /absolute/path/to/read-only-backup.db \
  --destination-url 'postgresql+psycopg://...' \
  --owner-map /absolute/path/to/owners.json \
  --mapping-output /absolute/path/to/identity-map.json \
  --plan-output /absolute/path/to/import-plan.json \
  --expected-source-sha256 '<sha256>'

uv run python -m backend.cli.import_legacy_sqlite apply \
  --source-sqlite /absolute/path/to/source.db \
  --backup-sqlite /absolute/path/to/read-only-backup.db \
  --destination-url 'postgresql+psycopg://...' \
  --owner-map /absolute/path/to/owners.json \
  --mapping /absolute/path/to/identity-map.json \
  --approved-plan /absolute/path/to/import-plan.json \
  --report-output /absolute/path/to/apply-report.json \
  --expected-source-sha256 '<sha256>' \
  --apply

uv run python -m backend.cli.import_legacy_sqlite verify \
  --source-sqlite /absolute/path/to/source.db \
  --destination-url 'postgresql+psycopg://...' \
  --owner-map /absolute/path/to/owners.json \
  --mapping /absolute/path/to/identity-map.json \
  --report-output /absolute/path/to/verification-report.json \
  --expected-source-sha256 '<sha256>'
```

Rules:

- `inspect` is source-only and read-only.
- `plan` is always a dry run. It may write only the explicitly named plan/mapping artifacts and never writes PostgreSQL. It records one UTC `imported_at` value that the approved apply will use for every imported `created_at`, `updated_at`, `joined_at`, and availability `updated_at` field.
- `apply` is the only writing subcommand. The literal `--apply` safety switch is additionally mandatory and noninteractive. Apply requires the separate backup, expected source SHA-256, owner map, identity mapping, and approved plan; it verifies every artifact hash and refuses to recompute decisions.
- Source, backup, destination, owner map, and output paths/URL are always explicit. There is no fallback to `DATABASE_PATH`, `DATABASE_URL`, repository `dnd_planner.db`, or a guessed home-directory path.
- Output files are created with restrictive permissions where supported and never overwritten. A deliberate `--replace-output` may be added only if it uses an atomic replacement and is separately tested.
- Console and JSON output use a redacted destination URL. Reports never contain a database password.
- Exit codes are stable: `0` verified success/idempotent no-op, `2` command/validation error, `3` source-data conflict, `4` unsafe/nonempty destination, `5` write/transaction failure, `6` post-import verification failure.

### Read-only source safeguards

1. Resolve the explicit source and backup to absolute real paths; require different files, regular-file type, and no output path alias.
2. Record file size, modification time, and streaming SHA-256 before opening.
3. Open SQLite through a URI with `mode=ro`, set `PRAGMA query_only=ON`, and never execute `CREATE`, `ALTER`, `INSERT`, `UPDATE`, `DELETE`, `VACUUM`, journal-mode, or optimization pragmas.
4. Inspect `sqlite_master`, `PRAGMA table_info`, and index metadata only. Require the expected table/columns and identify deviations in the report. Do not “repair” the source.
5. Read in a transaction and stream rows in deterministic key order.
6. Close the connection and recompute source size, modification time, and SHA-256. Any difference fails the run.
7. For apply, require the backup's SHA-256 to match the frozen source hash and report whether its filesystem write bits are absent. Filesystem permission checks are evidence, not a guarantee; operator confirmation of backup immutability remains required.

The tool must never inspect the repository's real SQLite database unless the operator explicitly supplies that exact path during a later authorized migration window.

### Source schema and data validation

The dry run is exhaustive and accumulates errors before exiting where safe:

- Require an `availability` table with `group_name`, `user_name`, `date`, and `status`. Report declared types, nullability, PK order, extra columns/indexes, and whether it matches the expected legacy contract.
- Report raw row count, distinct physical `(group,user,date)` count, distinct logical `(user,date)` count, distinct users/groups/dates/statuses, min/max date, and counts per status/user/group/month.
- Reject null/blank/noncanonical group and user names. Compare exact case-sensitive names against `legacy_contract.py`.
- Reject unknown groups, unknown users, and rows where the user is not a member of the named group. These rows are currently invisible or unsafe; silently dropping them would lose evidence.
- Parse dates with `date.fromisoformat`, require canonical `YYYY-MM-DD` round-trip, and list every invalid coordinate.
- Accept only exact `Available`, `Maybe`, and `No`; apply the status table above. Null, empty, `Unavailable`, case variants, or whitespace variants are fatal.
- Detect physical duplicate keys even if a malformed source lacks the expected PK.
- Collapse rows by exact logical `(user_name, day)`. Repeated rows with one identical status are a benign duplicate fact and are reported; two or more statuses are a fatal conflict with every source row listed.
- An empty availability table is valid: import the fixed profiles/groups/memberships and zero availability facts.
- Never trust the roadmap's historical 324 count as an assertion. The report provides the actual number and requires explicit operator review.

### Owner-map contract

The owner file is explicit JSON:

```json
{
  "version": 1,
  "groups": {
    "Green flag": "<exact member name>",
    "1D6": "<exact member name>",
    "Underdark": "<exact member name>"
  }
}
```

Parse while detecting duplicate JSON keys. Require exactly one key for every exact legacy group, no extra group, a nonblank exact user name, and membership of that user in the mapped group. Owners may own multiple groups; no owner is inferred from list order, availability activity, or a shared profile. Every nonowner membership imports as `member`; no organizer is guessed.

### Deterministic identity decision

| Strategy | Benefit | Cost/risk | Decision |
|---|---|---|---|
| UUIDv4 plus persisted mapping artifact | normal opaque random IDs; no relationship to names | a lost/partial artifact can change IDs on rehearsal or rerun; harder to prove idempotency before a ledger exists | use for all future application-created records, not legacy import |
| UUIDv5 from a fixed application namespace and canonical legacy key | same input always produces the same ID; easy independent verification and exact reruns | deterministic IDs reveal equality and require an immutable canonicalization contract | **recommended for the one-time legacy import** |

Commit one immutable namespace constant in `legacy_contract.py`:

```text
LEGACY_IMPORT_NAMESPACE = b47e7a21-6b6f-4c5d-a3d2-193b02d77d6f
```

Derive IDs as UUIDv5 over UTF-8 strings:

```text
user\0<Unicode-NFC exact legacy user name>
group\0<Unicode-NFC exact legacy group name>
```

Do not lowercase or trim identity inputs. Fail if two original strings normalize to the same NFC key. One exact profile name shared across groups maps to one `User`; membership records connect that user to each group. Future duplicate display names receive independent UUIDv4 IDs and are never auto-merged.

The mapping artifact remains mandatory even though IDs are reproducible. It contains namespace/version, source names, canonical keys, UUIDs, group membership order/role, owner decisions, status-map version, source hash, destination revision, the plan's `imported_at`, and sorted-record checksums.

Legacy source fields map exactly as follows:

- Users receive exact legacy `display_name`, `timezone='UTC'`, null email, null auth provider/subject, and the plan's `imported_at` for both timestamps.
- Groups receive exact legacy `name`, `timezone='UTC'`, null description, and the same two timestamps. The legacy application contains date-only facts and no timezone metadata; `UTC` is an explicit neutral placeholder, not an inferred user location.
- Memberships receive their exact legacy list position as zero-based `display_order`, the mapped owner gets `owner`, every other member gets `member`, and `joined_at=imported_at`.
- Availability receives the deterministic user UUID, parsed day, normalized status, and `updated_at=imported_at`.

Using the approved plan's one timestamp makes the complete expected rows—including audit fields—stable across apply, verification, and an idempotent rerun.

### Destination safety, transactionality, and idempotency

- Accept only a `postgresql+psycopg` destination. Connect and require Alembic revision exactly at repository head before any domain query.
- Start a serializable transaction and acquire a transaction-scoped PostgreSQL advisory lock derived from a fixed importer key so two imports cannot race.
- Count all four domain tables while locked. An empty set is writable. The `alembic_version` row does not make the destination “nonempty.”
- If any domain table is nonempty, load the complete expected dataset from the approved plan and compare every sorted row, including planned audit timestamps. If it is an **exact prior import**—same deterministic IDs, scalar fields, memberships/order/roles, owner choices, availability, and no extra rows—report `already_applied`, perform no writes, and exit `0`. This is a loud idempotent no-op, not a silent import into a nonempty database.
- Any partial, additional, or differing domain data is an unsafe nonempty destination. Report table counts and bounded mismatch samples, write nothing, and exit `4`. There is no `--force`, merge, truncate, or upsert mode in Phase 1.
- For an empty destination, insert users, groups, memberships, then global availability in one transaction. Flush after each entity class to expose constraints, but commit exactly once only after internal verification.
- Inject no `create_all` and run no migration from the importer.
- On any validation, insert, constraint, connection, or precommit verification failure, roll back the whole transaction. Tests must force a mid-import failure and assert all four domain tables remain empty.
- Preflight output paths for writability before beginning the database transaction. Generate artifacts in memory. After a successful commit, write each to a same-directory temporary file, fsync, and atomically rename. If final artifact publication fails after commit, emit an unmistakable recovery error; deterministic rerun will classify the destination as exact and regenerate artifacts without writing data.

### Import and verification artifacts

Human-readable console output and machine-readable JSON reports include:

- tool/report schema version, UTC start/end time, Git commit, Alembic revision, redacted destination;
- resolved source/backup paths, size/mtime/hash before and after, and source schema fingerprint;
- actual source statistics and every validation/conflict category;
- owner-map and status-map checksums;
- exact source-name-to-UUID mappings and membership order/role;
- planned inserts, exact-existing matches, skipped/no-op rows, and expected/actual counts for users, groups, memberships, and global availability;
- SHA-256 over canonical sorted JSON Lines for each entity table;
- SHA-256 over canonical logical `(legacy user, day, normalized status)` facts;
- per-user fact counts, min/max day, and per-user canonical availability checksum;
- SHA-256 over each compatibility projection `(group_name,user_name,date,legacy status)` and an aggregate projection;
- transaction outcome: `dry_run`, `applied`, `already_applied`, `rolled_back`, or `verification_failed`;
- bounded mismatch samples plus full mismatch count. No report may claim success if a mismatch is truncated from display.

Verification is stronger than counts:

1. Re-read target rows in a new read-only transaction after commit.
2. Require exact set equality for deterministic users/groups and all fields intended by import.
3. Require exact membership set, role, owner, and display order.
4. Require exact global availability tuple equality.
5. Reconstruct the legacy API projection for every imported group and every source month, plus the inclusive min/max admin range, and compare sorted rows to the validated source behavior.
6. Recompute all checksums and compare with the dry-run mapping/report.
7. Run the importer a second time and require the explicit `already_applied` no-op.

### Error behavior

| Condition | Required behavior |
|---|---|
| Missing/unreadable/defaulted source | fail before connecting destination |
| Source hash/stat changes during read | fail; no destination write |
| Backup missing/different for apply | fail; no destination write |
| Schema mismatch | detailed report and fail; never mutate source |
| Unknown/blank identity, bad date/status | list all safely discoverable errors and fail |
| Conflicting logical status | list every conflicting row and fail |
| Owner map missing/extra/invalid | fail before destination transaction |
| Destination unreachable/wrong driver/wrong revision | redacted error and fail |
| Empty destination | import once in one transaction |
| Exact prior import | explicit verified no-op, exit `0` |
| Partial/unrelated/nonmatching destination | fail closed; no force/merge/truncate |
| Constraint or injected mid-import failure | full rollback; destination remains empty |
| Post-commit verification mismatch | exit nonzero, retain evidence, prohibit cutover |
| Mapping/report publish failure after commit | report committed-but-artifact-failed state; deterministic verified rerun regenerates artifacts |

### Implementation sequence

1. Extract the exact immutable group/player/status contract without changing the legacy database behavior; prove equality with current group/database tests.
2. Implement source path resolution, read-only connection, schema inventory, metadata hashes, and exhaustive source validation.
3. Implement owner-map parsing with duplicate-key detection and UUIDv5 identity planning.
4. Implement canonical plan/mapping/report serialization and artifact hashes.
5. Implement destination revision/emptiness checks, advisory lock, one-transaction inserts, exact precommit checks, and rollback paths.
6. Implement independent verify and exact-prior-import no-op classification.
7. Add every synthetic SQLite and disposable PostgreSQL fixture/error case before any copy-based rehearsal.
8. Document artifact review, final apply, and recovery; run the complete Phase 0 quality gate to prove no runtime cutover occurred.

### Tests and commands

Generated fixtures cover empty source; canonical source; shared users; repeated same logical status across groups; conflicting statuses; every invalid status form; malformed dates; nulls/blanks; unknown group/user/nonmembership; malformed/missing/extra schema; duplicate physical rows; invalid/duplicate-key owner maps; source changing during read; destination at wrong revision; partial/nonmatching destination; exact rerun; injected transaction failure; and artifact publication failure.

```bash
uv run pytest -q backend/tests/test_import_legacy_sqlite.py
uv run pytest -q backend/tests/postgres/test_import_legacy_sqlite.py

# Rehearsal only, with generated fixture paths—not the real database
uv run python -m backend.cli.import_legacy_sqlite inspect ...
uv run python -m backend.cli.import_legacy_sqlite plan ...
uv run python -m backend.cli.import_legacy_sqlite apply ... --apply
uv run python -m backend.cli.import_legacy_sqlite verify ...

./scripts/check.sh
```

### CI requirements

CI creates its own SQLite fixture, owner map, outputs, and disposable PostgreSQL database. It runs plan, apply, verify, exact rerun, forced rollback, and representative fail-closed cases. No database artifact is committed or uploaded unless it is synthetic and contains no secrets. Keep every Phase 0 backend/frontend gate unchanged.

### Migration considerations

The importer requires the destination to be at the exact 1A Alembic head and never runs migrations itself. Import logic is data movement, not an Alembic data revision: owner decisions, source paths, and mapping artifacts are operator-specific and must not be embedded in a globally replayable migration. A future schema revision invalidates an old plan unless the plan format explicitly supports and verifies that revision.

### Rollback

An inspect/plan failure has no destination rollback because it performs no destination writes; retain its report and correct the input. Before commit, any apply failure rolls back to empty. After a successful rehearsal import, discard only the generated disposable PostgreSQL database; never truncate a shared destination. The runtime still uses SQLite, so importer code can be reverted without a service rollback.

### Definition of done

Phase 1B is done when all failure modes are tested, a synthetic rehearsal dry-run/apply/verify/rerun is exact, reports are operator-readable and machine-verifiable, the source file is provably unchanged, the existing app still runs on SQLite, and no real data has been opened.

### Explicit exclusions

No runtime SQLAlchemy adapter/cutover, automatic owner inference, email assignment, profile claims, merge mode, conflict precedence, dual writes, source repair, real database access, or hosted migration.

## Phase 1C compatibility and cutover plan

### Goal

Move the five existing endpoints to PostgreSQL-backed SQLAlchemy queries while keeping the current frontend unchanged and retaining a safe, explicitly timed rollback path.

### Exact file scope

| Action | File | Reason |
|---|---|---|
| Add | `backend/compatibility.py` | temporary name-shaped SQLAlchemy adapter and status translation |
| Modify | `backend/main.py` | inject SQLAlchemy sessions/runtime and route existing endpoints through adapter |
| Modify | `backend/config.py` | require `DATABASE_URL` for runtime after cutover; keep `DATABASE_PATH` for legacy tests/tools |
| Modify | `backend/db.py` | final app-state runtime/session dependency and revision check |
| Modify | `backend/tests/conftest.py` | support explicit legacy SQLite and SQLAlchemy TestClient factories without global leakage |
| Modify | `backend/tests/test_app_factory.py` | prove distinct SQLAlchemy app runtimes do not leak settings, pools, or data |
| Modify | `backend/tests/test_availability_api.py` | run canonical month/write/admin/global behavior against the compatibility runtime and promote invalid-status xfail only if approved |
| Modify | `backend/tests/test_groups.py` | preserve exact name/player shape and ordering against PostgreSQL |
| Modify | `backend/tests/test_health.py` | preserve the exact safe health response against the new app runtime |
| Add | `backend/tests/compatibility_contract.py` | shared assertions only when needed to run one contract against both persistence adapters |
| Add | `backend/tests/postgres/test_compatibility_api.py` | exact endpoint projection, fan-out idempotency, isolation, and startup tests |
| Modify | `.env.example` | mark `DATABASE_URL` as active runtime and `DATABASE_PATH` as legacy import/test only |
| Modify | `README.md` | PostgreSQL-first startup/migrate steps and compatibility caveats |
| Modify | `docs/LEGACY_IMPORT_RUNBOOK.md` | final maintenance window, verification, service switch, rollback clock |
| Modify | `.github/workflows/ci.yml` | start migrated PostgreSQL and run API contract through `TestClient` |
| Modify | `scripts/check.sh` | include PostgreSQL compatibility suite and preserve frontend gate |

Keep `backend/database.py` through at least one documented rollback window. Do not delete it or the legacy tests in Phase 1C. No frontend source file should change.

`backend/tests/test_database.py` remains unchanged as the direct legacy SQLite rollback oracle. If parameterizing an existing API file makes its SQLite intent harder to read, retain that file unchanged and put the PostgreSQL form entirely in `backend/tests/postgres/test_compatibility_api.py`; use `backend/tests/compatibility_contract.py` only for genuinely shared assertions.

### Dependencies

No new backend or frontend dependency is expected. Reuse the synchronous SQLAlchemy runtime and existing FastAPI/Pydantic/TestClient stack. Do not add a repository abstraction, dependency-injection package, async driver, query cache, frontend data library, or E2E framework.

### Compatibility adapter behavior

`backend/compatibility.py` exposes operations matching the current backend function boundary but receives a request-scoped `Session`; it has no configured global engine.

- **Groups:** query the three imported legacy groups, memberships, and users. Return exact names and `display_order`. Preserve the legacy group order from `legacy_contract.py`; fail startup/verification if any expected group is missing or ambiguous.
- **Month availability:** resolve one exact group name; unknown returns `[]`; select members joined to global availability in `[first_day, first_day_next_month)`; emit one row per member/day with the requested `group_name` and legacy status string.
- **Write availability:** resolve one exact group, exact user, and membership. Map `Available/Maybe/No` to normalized values and use PostgreSQL `INSERT ... ON CONFLICT (user_id, day) DO UPDATE`, explicitly updating `updated_at`. `null` deletes `(user_id, day)`. The group determines compatibility identity/validation but is not stored on availability.
- **Frontend fan-out:** repeated posts for the same user/day from each membership perform the same idempotent upsert/delete. Every response remains `{"status":"success","new_state":<input>}`.
- **Admin range:** filter global availability with `day >= start AND day <= end`, join every membership, and emit one legacy-shaped row per group membership. Keep it anonymous until auth work; do not rename it or add `/v1` here.
- **Health:** retain exact `{"status":"ok"}` and do not include database details. A separate readiness route belongs to the production operations phase unless explicitly authorized.
- **Removal marker:** document all five endpoints as temporary compatibility routes in the module docstring and README, link their removal to Phase 2, and emit one structured startup warning that compatibility mode is active. Do not log per-request user names, dates, statuses, or availability payloads merely to count legacy usage.
- **Transactions:** reads close without commit. Each logical POST is one transaction. Integrity failures are rolled back and translated to a safe API error without exposing SQL, URLs, or IDs.
- **Ordering:** tests compare content where the current contract is unordered, but `/groups` and player arrays preserve their current explicit order. Do not accidentally promise new ordering for availability rows.

The adapter maps normalized output exactly:

```text
available -> Available
maybe -> Maybe
unavailable -> No
```

No code sends `Unavailable` over the compatibility API.

### App-factory and startup isolation

`create_app(app_settings=None, database_runtime=None)` remains the public factory:

1. Resolve settings once per factory call.
2. If a runtime is supplied by a test, verify it belongs to those settings and use it.
3. Otherwise create a runtime from required `DATABASE_URL` without connecting at import time.
4. Lifespan performs `SELECT 1` and reads `alembic_version`; mismatch fails before serving traffic and tells the operator to run `uv run alembic upgrade head` with a redacted target.
5. Store runtime and settings only on that app's state.
6. Dispose the engine at lifespan shutdown.

Two TestClient applications with distinct disposable databases must not share engine, pool, sessionmaker, settings, rows, or lifecycle. Importing `backend.main` must not connect, migrate, or create tables.

### Necessary compatibility approval

Before changing the runtime, approve both relationally necessary write-boundary changes:

1. Noncanonical statuses change from accidental acceptance to `422`; promote the existing strict xfail to a passing regression.
2. Unknown group/user/nonmember writes change from accidental invisible SQLite persistence to `422`.

These are not Phase 2's general API redesign. They are the narrow consequence of enforcing the Phase 1 foreign keys/status check. If either is not approved, keep the app on SQLite and defer the write cutover; do not weaken the target constraints or fake successful writes.

### Implementation and verification sequence

1. Implement adapter reads and run side-by-side contract tests against synthetic equivalent SQLite/PostgreSQL fixtures.
2. Implement writes and redundant frontend fan-out tests.
3. Switch `create_app` to required `DATABASE_URL`; retain legacy modules/tests.
4. Run complete backend and frontend gates against disposable PostgreSQL.
5. Start both services locally and verify `/api/test-health`, `/api/groups`, month reads, each status transition, clear, shared-profile projection, and inclusive admin range through Next.js.
6. Perform at least two full migration rehearsals from a copy of the source, including exact idempotent rerun and rollback rehearsal. Do not use the real file yet.
7. Schedule a maintenance/no-write window and freeze the legacy app.
8. Create and independently verify the final read-only backup. Record source SHA-256 and operator-approved owner map.
9. Run final dry run; compare to prior rehearsal and have the operator approve all actual counts/conflicts/mappings.
10. Run apply and independent verify. Any mismatch is no-go.
11. Start the new release with `DATABASE_URL`; keep browser writes disabled during an acceptance smoke test.
12. If smoke passes, enable writes and record the cutover time. If smoke fails before writes, stop the new release and restart the previous SQLite release against the unchanged source.

### Tests

Run the existing API contract with temporary SQLite as the legacy oracle and with a migrated disposable PostgreSQL database through `TestClient`. Use direct SQLAlchemy sessions for projection edge cases and transaction assertions. Cover redundant frontend fan-out, shared users, exact status translation, clear, ambiguous names, unknown-group read, approved invalid writes, inclusive admin ranges, health, revision mismatch, two-app isolation, and import/startup no-DDL behavior. Keep frontend lint/typecheck/build and perform the documented read-only browser/proxy smoke without adding a new framework.

### Local commands

```bash
docker compose -f compose.postgres.yml up -d --wait postgres
uv sync --frozen
uv run alembic upgrade head
uv run pytest -q
uv run ruff check backend
uv run ruff format --check backend
npm --prefix frontend ci --no-audit --no-fund
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build

# Start after migration/import verification
uv run python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
npm --prefix frontend run dev -- --hostname 0.0.0.0 --port 3000
curl --fail http://127.0.0.1:8000/test-health
curl --fail http://127.0.0.1:3000/api/test-health
curl --fail http://127.0.0.1:3000/api/groups
```

### CI requirements

- Existing legacy SQLite tests remain and continue proving old behavior.
- PostgreSQL service is migrated with Alembic before SQLAlchemy API tests.
- Run the same API contract against a PostgreSQL TestClient app with isolated settings.
- Import a synthetic fixture, start the app over its target, and verify compatibility projections.
- Keep the full frontend lint, typecheck, and production build. A browser E2E framework is not introduced in Phase 1; the proxy smoke is a documented local/release check.

### Migration considerations

The target must already be at the exact initial head and contain an exact verified import before the service switch. Phase 1C adds no schema revision unless implementation discovers a genuine schema defect; in that event stop, amend/review 1A/1B compatibility, and rehearse from an empty destination again rather than slipping a migration into the runtime-cutover change. FastAPI never upgrades the database on startup.

### Rollback

- **Before writes are enabled:** stop the SQLAlchemy release, restore the previous application release/configured `DATABASE_PATH`, and restart against the unchanged frozen SQLite source. Keep PostgreSQL and all artifacts for diagnosis.
- **After PostgreSQL accepts writes:** an automatic rollback to SQLite would lose those writes. Do not do it. Re-enter maintenance, record the cutover interval, compare changed PostgreSQL facts with the frozen source, and make an explicit reconcile-or-forward-fix decision. Phase 1 intentionally has no dual-write or reverse importer.
- **Data error discovered after cutover:** stop writes, preserve both stores and every manifest, classify whether the error came from source interpretation, mapping, or subsequent PostgreSQL writes, and produce a separately reviewed corrective data plan. Prefer a forward correction with before/after manifests; returning to SQLite requires explicit reconciliation of every post-cutover fact and is outside this Phase 1 plan.
- Never use Alembic downgrade or `docker compose down --volumes` as a production rollback.
- Retain the source and backup read-only for the operator-approved retention period. Do not modify/delete `dnd_planner.db` as part of cleanup.

### Definition of done

- Existing frontend runs unchanged against PostgreSQL through `/api/*`.
- Existing compatibility endpoints preserve canonical status cycle, global shared-user behavior, response shapes, unknown-group read, inclusive admin range, and safe health output.
- Approved status/unknown-write exceptions are explicit tests, not hidden behavior changes.
- Runtime startup is isolated and performs no DDL.
- Final import and independent verification artifacts match exactly.
- A no-write rollback rehearsal has succeeded and the post-write rollback limitation is documented.

### Explicit exclusions

No `/v1`, auth, authorization, profile claiming/email assignment, group CRUD, invitations, subscriptions, sessions, frontend state changes, deployment, hosted PostgreSQL provisioning, dual writes, reverse importer, or deletion of legacy data.

## Test matrix

| Area | 1A | 1B | 1C | Technology/isolation |
|---|---|---|---|---|
| Existing SQLite database functions | all existing tests unchanged | unchanged plus `legacy_contract` parity | retained as rollback oracle | pytest + unique `tmp_path` SQLite file; never default DB |
| Existing FastAPI routes | all existing tests unchanged | unchanged | contract run against PostgreSQL adapter | FastAPI `TestClient` lifespan + explicit Settings/runtime |
| App factory isolation | SQLite path isolation | unchanged | two engines/sessionmakers/databases isolated | two simultaneous/sequential TestClients |
| Models and relationships | full | regression | regression | disposable PostgreSQL migrated by Alembic |
| UUID behavior | v4 type/default and native PG type | v5 mapping determinism | response remains name-shaped | Python UUID assertions + PG catalog |
| Enum/check behavior | role/status valid and invalid writes | legacy-to-normalized map | API translations | Session transactions + PG constraint errors |
| Email/auth constraints | null imported identities, pair/unique/email checks | imported values null | no auth behavior | PostgreSQL |
| Owner invariant | create/transfer/remove/delete concurrency-oriented cases | exact owner map | no group endpoints yet | Session + `SELECT FOR UPDATE` + partial index |
| Availability global key | PK/status/date/index | conflict collapse | shared users visible in every group | PostgreSQL Session and API |
| Alembic | base→head, inspect, check, head→base→head | wrong revision rejection | startup revision check | unique disposable PostgreSQL database |
| Source inspection | n/a | exhaustive generated variants | final dry run | temporary synthetic SQLite files opened `mode=ro` |
| Import transaction | n/a | empty apply, forced failure rollback, exact rerun, unsafe nonempty rejection | final rehearsal evidence | one SQLAlchemy Session/transaction + advisory lock |
| Import verification | n/a | exact rows, checksums, projections, artifact errors | compare final reports | canonical sorted JSON + SHA-256 |
| Status cycle | current strict xfail remains | remains | canonical cycle passes; invalid test changes only with approval | parametrized API contract |
| Date behavior | current malformed/inclusive/month tests | invalid/import date tests | identical API behavior | `date`, TestClient, PostgreSQL |
| Frontend | existing lint/typecheck/build | same | same, plus manual proxy smoke | npm CI gate + running Next/FastAPI |
| CI | add PG model/migration gate | add synthetic importer gate | add PostgreSQL API gate | GitHub Actions PostgreSQL service |

No new-schema test may call `create_all`. Test database creation itself uses PostgreSQL administrative `CREATE DATABASE` only for a guarded randomly named test target; schema creation always uses Alembic.

## Verification and rollback

### Evidence required after each subphase

| Subphase | Verification evidence | Rollback proof |
|---|---|---|
| 1A | lock check; current full gate; exact PG catalog assertions; Alembic up/down/up; app still writes temp SQLite in tests | prior app starts without PostgreSQL; no real SQLite diff |
| 1B | synthetic dry-run/apply/verify/rerun reports; source before/after hashes equal; forced failure leaves target empty | discard exact generated test DB; runtime still SQLite |
| 1C | side-by-side fixture projections; final import exact checksums; Next.js proxy smoke; no-write cutover rehearsal | previous release restarts against frozen SQLite before writes |

### Real-data verification gates

Counts alone are insufficient. Before real cutover, require all of the following:

- source and separate backup SHA-256, byte size, mtime, and operator storage location recorded;
- actual source schema and every rejected/unknown/conflicting row category reviewed;
- actual owner map reviewed group by group;
- exact UUID mapping artifact archived;
- exact entity tuple sets and per-table checksums equal;
- exact logical user/day/status facts and checksums equal;
- exact membership order/role/owner sets equal;
- exact legacy projection per group/month and full inclusive range equal;
- importer second run is a verified no-op;
- complete API regression, Ruff, frontend lint/typecheck/build pass from the cutover commit;
- read-only UI/proxy smoke passes before writes are enabled;
- previous release, environment, source file, and restore command are available and rehearsed.

### Rollback clock

Define three states in the runbook:

1. **Legacy live:** SQLite is writable; PostgreSQL rehearsal data is disposable.
2. **Maintenance/no writes:** source is frozen, backed up, imported, verified, and the new app is smoke-tested. Rollback is safe by restarting the old release.
3. **PostgreSQL live:** first new write has occurred. SQLite is now a historical backup, not an automatic rollback target. Recovery favors forward-fix; any reverse reconciliation requires a separate reviewed plan.

Do not claim cutover complete until state 3 is stable for the agreed observation window and artifacts have been retained. Do not delete or modify either SQLite copy.

## Risks and decisions

| Topic | Recommendation | Reason | Consequence / operator input |
|---|---|---|---|
| Subphase size | merge 1A, 1B, 1C separately | preserves runnable checkpoints and reviewability | operator approves each go/no-go |
| Backend layout | keep shallow `backend/` | avoids premature roadmap-wide restructure | future modularization remains incremental |
| SQLAlchemy mode | synchronous 2.x + Psycopg 3 | matches roadmap/current workload and simpler transaction semantics | no async engine/session |
| PostgreSQL version | local/CI major 17 | supported through 2029 and mature | re-evaluate production provider version before deployment |
| Schema ownership | Alembic only | deterministic reviewed evolution | never `create_all`; startup fails if revision is wrong |
| Runtime config | `DATABASE_URL` new runtime; `DATABASE_PATH` legacy only | prevents semantic ambiguity | URL required only at 1C cutover |
| Application IDs | UUIDv4 | opaque/simple at this scale | generated in Python |
| Legacy IDs | fixed-namespace UUIDv5 + artifact | deterministic rehearsal and idempotency | operator accepts equality leakage for imported public identities |
| Enum storage | constrained strings | easier evolution/downgrade than PG native enum | explicit checks/migrations required |
| Unclaimed identities | both auth fields and email nullable | imported public profiles have no verified account identity | claiming remains Phase 3; importer must not invent values |
| Email uniqueness | nullable case-insensitive unique expression index | imports are unclaimed; future claimed email collision protected | active/inactive reuse deferred |
| Deactivation | omit in Phase 1 | lifecycle semantics do not yet exist | defer to Phase 3/4; restrict member hard delete |
| Group names | not globally unique | correct future SaaS domain | temporary compatibility adapter requires unambiguous three legacy names |
| Member ordering | persist `display_order` | `/groups` player order is visible today | importer must map every position exactly |
| Exactly one owner | partial unique index + locked transaction service | DB alone can enforce only at most one | operator supplies exhaustive owner map |
| Global availability | `(user_id, day)` | preserves explicit product rule and removes duplicate storage | conflicting source facts block import |
| Legacy status `No` | map to `unavailable`; output `No` | resolves UI wording mismatch without API break | `Unavailable` is never accepted as source/API value |
| Invalid statuses | reject in 1C only with approval | target check cannot store arbitrary values | otherwise no write cutover; xfail remains through 1B |
| Unknown write identities | reject in 1C only with approval | FKs cannot represent invisible legacy garbage safely | otherwise no write cutover |
| Source safety | explicit `mode=ro`, query-only, before/after hash | importer must not mutate evidence | operator supplies source and separate backup paths |
| Source selection | no default or `DATABASE_PATH` fallback | prevents accidentally opening the repository/real file | operator supplies an absolute source path every run |
| Nonempty target | exact prior import is read-only no-op; anything else fails | no silent merge/truncation | operator provisions a migrated empty destination |
| Import transaction | one serializable transaction + advisory lock | atomic and race-resistant | no batch partial commits |
| SQLite/PostgreSQL differences | retain SQLite only as legacy oracle; prove new constraints on PostgreSQL | SQLite cannot establish native UUID, FK-action, or partial-index production behavior | CI PostgreSQL is mandatory from 1A |
| Migration downgrade | destructive reverse order only on disposable databases | useful migration proof, unsafe runtime rollback | production rollback uses old release/backup, never downgrade |
| Cutover rollback | smoke while writes disabled | SQLite rollback is safe only before first PG write | operator selects maintenance and observation windows |
| Compatibility endpoint lifespan | mark temporary and remove in Phase 2 after ID routes are adopted | prevents name-shaped anonymous routes becoming permanent | startup warning/docs remain until measured removal |
| Frontend | no product code change | compatibility adapter exists to protect it | any frontend diff requires separate justification |
| Branch name | use `master` for CI/cutover references | current repository and workflow use `master`; older roadmap `main` text is stale | do not rename the default branch inside Phase 1 |

## Recommended Phase 1A Codex prompt outline

Use this as an outline for a later implementation prompt, not as authorization now:

1. State: “Implement only Phase 1A from `docs/PHASE_1_IMPLEMENTATION_PLAN.md`; do not begin 1B/1C.”
2. Require a clean status/diff inspection and explicit confirmation that `dnd_planner.db` will not be opened or modified.
3. Limit file scope to the Phase 1A table in this document.
4. Require synchronous SQLAlchemy, the four exact models, checks/indexes/FK actions, owner service, and app-factory-safe runtime construction.
5. Require Alembic-only schema creation and the exact initial migration/up/down order.
6. Require the PostgreSQL 17 one-service Compose design; prohibit application containers.
7. Require current FastAPI runtime to remain SQLite and prohibit edits to existing routes/frontend.
8. Require `uv` lock updates with only the three specified direct dependencies and no unrelated upgrades.
9. Require guarded disposable PostgreSQL tests, exact catalog checks, existing SQLite regression tests, Ruff, frontend lint/typecheck/build, and CI.
10. Require a completion report listing every file/command/result, any skipped verification, and a `git diff -- dnd_planner.db` no-change confirmation.
11. State: “Do not commit, push, access real data, or begin importer/cutover work.”

## Required operator inputs before Phase 1B

No rehearsal against real or copied real data may begin until the operator explicitly supplies and approves:

- **Source path:** exact absolute path to the frozen legacy SQLite source; never inferred from repository defaults.
- **Backup path:** exact absolute path to a separate timestamped read-only backup, outside the repository, plus retention/storage expectations.
- **Expected source hash:** independently computed SHA-256 after writes stop.
- **Owner assignment:** one exact current member for each of `Green flag`, `1D6`, and `Underdark` in the versioned owner-map format.
- **Group identity confirmation:** confirmation that the three exact, case-sensitive group names and membership ordering in this document are authoritative.
- **Profile identity confirmation:** confirmation that exact case-sensitive shared names denote one person across groups and that no two distinct people currently share a name.
- **Destination:** explicit redacted PostgreSQL server/database identity, expected Alembic revision, and confirmation that all four domain tables are empty or an exact verified prior rehearsal.
- **Status map approval:** exact `Available→available`, `Maybe→maybe`, `No→unavailable`, no-row→no-row mapping; unknown values must block.
- **Identity strategy approval:** fixed namespace UUIDv5 for imported users/groups, UUIDv4 for future records, and retention location for the mapping artifact.
- **Compatibility exception approval for 1C:** whether invalid statuses and unknown/nonmember writes may change to `422`; lack of approval blocks write cutover but does not block synthetic 1B work.
- **Cutover window:** maintenance start, no-write smoke duration, responsible operator, rollback decision deadline, observation window, and artifact/backup retention period.
- **Recovery authority:** who decides forward-fix versus rollback after the first PostgreSQL write.

Never place database passwords, real owner maps, mapping artifacts, reports containing personal paths/data, or backup files in Git.

## Go/no-go checklist

Migration against real data is **NO-GO** unless every applicable box is evidenced:

- [ ] Phase 1A was implemented and reviewed separately; existing SQLite/API/frontend gates pass.
- [ ] PostgreSQL model constraints and exact indexes pass on a disposable PostgreSQL 17 database.
- [ ] Alembic base→head, `check`, head→base→head passes without `create_all`.
- [ ] FastAPI import/startup performs no SQLAlchemy DDL and app-factory isolation passes.
- [ ] Phase 1B was implemented and reviewed separately; runtime still uses SQLite.
- [ ] Synthetic importer tests cover every source, owner, destination, transaction, rerun, and artifact failure listed above.
- [ ] At least two copy-based rehearsals produced exact dry-run/apply/verify/idempotent-no-op results.
- [ ] The explicitly supplied source remained byte-for-byte unchanged during each rehearsal.
- [ ] Final source writes are stopped and the maintenance window is active.
- [ ] A separate read-only backup exists outside the repository; source and backup SHA-256 match and are independently recorded.
- [ ] Actual source schema/counts/statuses/dates/names are reviewed; the roadmap's historical 324 count is not blindly assumed.
- [ ] There are zero unknown identities, invalid dates/statuses, malformed rows, and logical status conflicts—or the migration remains blocked. No manual silent cleanup is allowed.
- [ ] Owner map is exhaustive, exact, and each owner is a current member; no owner was guessed.
- [ ] Group/profile identity assumptions and UUIDv5 strategy are explicitly approved.
- [ ] Destination URL is explicit/redacted, revision equals head, and domain tables are empty or an exact verified prior import.
- [ ] Dry-run source hash, owner/status map hashes, UUID mappings, entity checksums, and compatibility projection checksums are archived and approved.
- [ ] Apply completed in one transaction and independent post-commit verification exactly matches the dry run.
- [ ] Immediate rerun reported a verified `already_applied` no-op with no writes.
- [ ] Phase 1C side-by-side compatibility tests pass for groups, month reads, canonical cycle/clear, shared users, admin inclusive range, unknown-group read, health, and redundant frontend fan-out.
- [ ] The strict invalid-status and unknown-write compatibility exceptions have explicit approval; otherwise write cutover remains blocked.
- [ ] Full Ruff, pytest, frontend `npm ci`, lint, typecheck, production build, and CI pass at the exact cutover commit.
- [ ] Next.js `/api/test-health`, `/api/groups`, reads, writes, clear, and cross-group behavior pass in a no-write/local or staged smoke.
- [ ] Previous application release, `DATABASE_PATH` configuration, frozen source, restart commands, and responsible rollback operator are ready.
- [ ] The team understands that rollback to SQLite is automatic only before the first PostgreSQL write; after that, maintenance plus reconciliation/forward-fix is required.
- [ ] No command will delete, modify, migrate in place, or commit `dnd_planner.db` or its backup.

If any checked assertion cannot be independently demonstrated, stop before real import or runtime cutover. Do not weaken constraints, infer owner/data decisions, use a force flag, or proceed based only on row counts.
