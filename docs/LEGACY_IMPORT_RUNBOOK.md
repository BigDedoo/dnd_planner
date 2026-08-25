# Legacy import runbook

Phase 1B implements the explicit legacy importer. Normal FastAPI requests use PostgreSQL through `DATABASE_URL`; the legacy `sqlite3` implementation remains source-only tooling for synthetic importer evidence. The Phase 1C normalization follow-up adds an optional, explicit policy for audited legacy aliases and ignored groups. Real-data work still requires separate operator authorization and operator-controlled inputs.

## Runtime separation

- **Normal runtime:** FastAPI uses PostgreSQL through `DATABASE_URL` and validates connectivity and the exact Alembic head before serving requests. Startup does not inspect historical group names or memberships.
- **Legacy source/test implementation:** `backend/database.py` continues using explicit synthetic SQLite paths for importer tests; normal FastAPI startup never falls back to it.
- **Import tool:** every source, backup, output, owner map, and destination environment-variable name remains explicit. The tool does not read application settings and never runs Alembic.

The obsolete anonymous compatibility routes are not part of the normal runtime. `MUTATIONS_ENABLED=false` disables modern authenticated writes; the exact `{"status":"ok"}` liveness response remains available.

## Safety contract

- PostgreSQL must already be at the exact Phase 1A Alembic head, `0001_phase_1_domain_schema`.
- FastAPI startup validates that revision but never upgrades it automatically.
- Importer commands never run Alembic and never create, drop, or truncate schema objects.
- Every source, backup, owner map, normalization policy, artifact, and destination environment-variable name is explicit. There are no path or database defaults.
- Source SQLite files are opened with URI read-only mode, immutable handling, and `PRAGMA query_only=ON`. Size, nanosecond modification time, and streaming SHA-256 are recorded before and after each read.
- `apply` is the only writing command and additionally requires `--apply`.
- A destination may be empty or an exact prior import. Any partial, additional, or differing domain row is rejected.
- No real source, backup, owner assignment, normalization policy, hash, path, credential, or generated artifact belongs in Git.

Use `/.local/legacy-import/` only as an ignored workspace for synthetic examples and generated artifacts. Real sources and backups must ultimately remain outside the repository in separately approved storage.

## Synthetic workspace

```bash
mkdir -p "$PWD/.local/legacy-import"
chmod 700 "$PWD/.local/legacy-import"
```

The test suite creates valid synthetic SQLite inputs automatically. Do not derive examples from an application database.

For a synthetic rehearsal, place explicitly generated files under the ignored directory:

```text
.local/legacy-import/
  synthetic-source.sqlite
  synthetic-backup.sqlite
  owners.json
  normalization-policy.json
  inspect-report.json
  identity-map.json
  import-plan.json
  plan-report.json
  apply-report.json
  verification-report.json
```

Source and backup must be different regular files with identical approved SHA-256 values. Filesystem write-bit reporting is evidence only; it does not prove immutability.

## Owner map

Owner assignments are mandatory operator input and are never inferred. Use exact current member names:

```json
{
  "version": 1,
  "groups": {
    "Green flag": "<EXACT MEMBER NAME>",
    "1D6": "<EXACT MEMBER NAME>",
    "Underdark": "<EXACT MEMBER NAME>"
  }
}
```

Duplicate keys, missing or extra groups, blank/non-string owners, unknown users, and nonmembers are rejected. Nonowners import as `member`; no organizer role is inferred.

## Legacy normalization policy

The optional normalization policy is a strict versioned JSON object. For real-data operations, create it in private operator-controlled storage outside Git, review it independently, and pass the exact same file to `inspect`, `plan`, `apply`, and `verify`. Do not add a real policy or its generated reports to the repository.

Generic synthetic example:

```json
{
  "version": 1,
  "ignored_groups": ["Legacy Admin"],
  "group_aliases": {
    "Legacy Dice": "1D6"
  },
  "user_aliases": {
    "Legacy Player": "Quentin"
  },
  "prefer_canonical_on_conflict": true
}
```

Aliases may target only the committed canonical groups and users. Canonical names cannot be remapped or ignored. Self aliases, cycles, duplicate keys, ambiguous ignored/aliased groups, malformed fields, and extra fields are rejected.

Normalization is deterministic and never changes the SQLite file:

1. Rows in explicitly ignored groups are excluded from migration facts but retained in the audit report.
2. Explicit user aliases are resolved to canonical users.
3. Explicit group aliases are resolved to canonical groups.
4. Rows collapse to the global `(canonical user, day)` key.

When `prefer_canonical_on_conflict` is `true`, an exact canonical-user row wins over an alias-user row for that user/day. Among rows for one normalized group, an exact canonical-group row wins over its group-alias row. These are the only automatic precedence rules. Differing statuses between equally canonical surviving rows remain fatal conflicts; source order, alphabetic order, recency, and status value never decide a conflict.

The policy's canonical SHA-256 and exact file SHA-256 are embedded in inspection reports, identity mappings, plans, apply reports, and verification reports. Apply and verify require the explicit policy file whenever the approved artifacts contain one. Any semantic or byte-level policy change invalidates those artifacts.

Omitting `--normalization-policy` preserves the original strict Phase 1B behavior and original artifact shape.

## Destination credentials

Keep credentials out of command arguments and shell history by putting the URL in an explicitly named environment variable supplied through an appropriate secret-loading mechanism:

```bash
export IMPORT_DESTINATION_URL='postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<explicit-disposable-database>'
```

Every PostgreSQL command must include:

```text
--destination-url-env IMPORT_DESTINATION_URL
```

The CLI resolves only that exact variable. It never falls back to `DATABASE_URL`, application settings, or a guessed name. Diagnostics and JSON artifacts redact the password.

## Inspect, plan, apply, verify

Set the synthetic workspace and independently calculated synthetic source hash:

```bash
work="$PWD/.local/legacy-import"
source_sha256='<SHA-256 OF THE EXPLICIT SYNTHETIC SOURCE>'
normalization_policy="$work/normalization-policy.json"
```

Inspect performs source-only validation and never connects to PostgreSQL:

```bash
uv run python -m backend.cli.import_legacy_sqlite inspect \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --normalization-policy "$normalization_policy" \
  --report-output "$work/inspect-report.json"
```

Plan is the dry run. It validates the source, backup, owner map, destination revision/state, deterministic identities, and expected rows without writing domain data:

```bash
uv run python -m backend.cli.import_legacy_sqlite plan \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --backup-sqlite "$work/synthetic-backup.sqlite" \
  --destination-url-env IMPORT_DESTINATION_URL \
  --owner-map "$work/owners.json" \
  --normalization-policy "$normalization_policy" \
  --mapping-output "$work/identity-map.json" \
  --plan-output "$work/import-plan.json" \
  --report-output "$work/plan-report.json" \
  --expected-source-sha256 "$source_sha256"
```

Review and retain every plan artifact before apply. `import-plan.json` contains the one UTC `imported_at` value used for all imported audit timestamps and the exact expected rows/checksums. `identity-map.json` records the fixed UUIDv5 mappings, memberships, roles, source hash, status-map version, normalization-policy evidence when supplied, destination revision, and checksums. Reports preserve every physical row's original coordinate and disposition while separately reporting normalized facts, ignored rows, alias counts, resolved precedence conflicts, remaining conflicts, and bounded destination mismatch examples with complete mismatch counts.

Apply consumes the approved artifacts and writes in one serializable, advisory-locked transaction:

```bash
uv run python -m backend.cli.import_legacy_sqlite apply \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --backup-sqlite "$work/synthetic-backup.sqlite" \
  --destination-url-env IMPORT_DESTINATION_URL \
  --owner-map "$work/owners.json" \
  --normalization-policy "$normalization_policy" \
  --mapping "$work/identity-map.json" \
  --approved-plan "$work/import-plan.json" \
  --report-output "$work/apply-report.json" \
  --expected-source-sha256 "$source_sha256" \
  --apply
```

Verify re-reads the committed target in a fresh transaction and compares exact entities, ownership/order, global availability, audit timestamps, logical facts, compatibility projections, and every approved checksum:

```bash
uv run python -m backend.cli.import_legacy_sqlite verify \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --destination-url-env IMPORT_DESTINATION_URL \
  --owner-map "$work/owners.json" \
  --normalization-policy "$normalization_policy" \
  --mapping "$work/identity-map.json" \
  --approved-plan "$work/import-plan.json" \
  --report-output "$work/verification-report.json" \
  --expected-source-sha256 "$source_sha256"
```

Run `apply` again with a new report path. The expected result is `already_applied`: all expected rows match, no rows are written, and the command exits successfully.

Artifacts are canonical UTF-8 JSON with sorted keys, deterministic ordering, SHA-256 checksums, and restrictive permissions where supported. Existing output files are never overwritten; use a new path for every attempt.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Verified success or exact `already_applied` no-op |
| `2` | Command, artifact, schema, data-validation, or configuration error |
| `3` | Conflicting logical source facts |
| `4` | Unsafe or nonmatching nonempty destination |
| `5` | Database write/transaction failure; pre-commit work rolled back |
| `6` | Post-commit verification or artifact-publication failure |

An error recorded in a report never produces exit code `0`.

## Rollback and recovery

Before commit, any validation, constraint, connection, serialization, injected, or internal verification failure rolls back the entire transaction. All four domain tables must remain empty.

After commit, failure to publish the apply report cannot roll back committed data. The CLI reports a committed-but-artifact-publication-failed error. Fix the output-path problem and rerun the same approved plan with a new report path; the deterministic rerun must classify the destination as an exact prior import, write no domain data, and regenerate evidence.

For a disposable synthetic database created by the guarded pytest fixture, allow fixture teardown to terminate connections and drop only its exact randomly generated `dnd_planner_test_*` database. For a separately provisioned synthetic destination, verify its exact approved disposable name and remove only that database through the PostgreSQL maintenance connection. Never delete, truncate, reset, or merge into the normal application database.

Alembic downgrade destroys schema and is not a production rollback. `docker compose down --volumes` destroys local volume data and is never part of real-data recovery. A later real-data rehearsal requires separate authorization, frozen source and backup evidence, explicit owner assignments, operator review of discovered facts, and an approved rollback window.

## Future cutover sequence (not authorized by Phase 1C-A)

The later operator-controlled cutover is deliberately split into a no-write state and a post-write state:

```text
set MUTATIONS_ENABLED=false
-> freeze and independently back up the approved source
-> run explicit inspect/plan/apply/verify
-> start FastAPI against the verified PostgreSQL target
-> smoke-test health, authenticated UUID-based routes, and the Next.js `/api` proxy
-> set MUTATIONS_ENABLED=true only after approval
```

Before the first PostgreSQL write, rollback means stopping the PostgreSQL release and restarting the retained SQLite release against the unchanged frozen source. After PostgreSQL accepts writes, SQLite is historical evidence rather than an automatic rollback target; reconciliation or a reviewed forward fix is required. Phase 1 has no dual-write or reverse-import path.

Do not execute this sequence, select a real source, request real owner assignments, or configure a production target as part of Phase 1C-A.

## Verification commands

```bash
uv run pytest -q backend/tests/test_import_legacy_sqlite.py
uv run pytest -q backend/tests/postgres/test_import_legacy_sqlite.py
uv run pytest -q backend/tests/postgres/test_runtime_security.py
./scripts/check.sh
```

Without `TEST_DATABASE_ADMIN_URL`, source-only tests still run and the script warns that PostgreSQL importer and authenticated-runtime validation were skipped. CI provides PostgreSQL 17 and requires every PostgreSQL test to execute with zero skips.
