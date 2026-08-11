# Legacy import runbook

Phase 1B implements and tests the legacy importer with generated synthetic SQLite files only. It does not authorize selecting real data. FastAPI still runs on the legacy `sqlite3` implementation through `DATABASE_PATH`; no endpoint, frontend behavior, or runtime database has changed.

## Safety contract

- PostgreSQL must already be at the exact Phase 1A Alembic head, `0001_phase_1_domain_schema`.
- Importer commands never run Alembic and never create, drop, or truncate schema objects.
- Every source, backup, owner map, artifact, and destination environment-variable name is explicit. There are no path or database defaults.
- Source SQLite files are opened with URI read-only mode, immutable handling, and `PRAGMA query_only=ON`. Size, nanosecond modification time, and streaming SHA-256 are recorded before and after each read.
- `apply` is the only writing command and additionally requires `--apply`.
- A destination may be empty or an exact prior import. Any partial, additional, or differing domain row is rejected.
- No real source, backup, owner assignment, hash, path, credential, or generated artifact belongs in Git.

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
```

Inspect performs source-only validation and never connects to PostgreSQL:

```bash
uv run python -m backend.cli.import_legacy_sqlite inspect \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --report-output "$work/inspect-report.json"
```

Plan is the dry run. It validates the source, backup, owner map, destination revision/state, deterministic identities, and expected rows without writing domain data:

```bash
uv run python -m backend.cli.import_legacy_sqlite plan \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --backup-sqlite "$work/synthetic-backup.sqlite" \
  --destination-url-env IMPORT_DESTINATION_URL \
  --owner-map "$work/owners.json" \
  --mapping-output "$work/identity-map.json" \
  --plan-output "$work/import-plan.json" \
  --report-output "$work/plan-report.json" \
  --expected-source-sha256 "$source_sha256"
```

Review and retain every plan artifact before apply. `import-plan.json` contains the one UTC `imported_at` value used for all imported audit timestamps and the exact expected rows/checksums. `identity-map.json` records the fixed UUIDv5 mappings, memberships, roles, source hash, status-map version, destination revision, and checksums. Reports include discovered source facts and bounded mismatch examples with complete mismatch counts.

Apply consumes the approved artifacts and writes in one serializable, advisory-locked transaction:

```bash
uv run python -m backend.cli.import_legacy_sqlite apply \
  --source-sqlite "$work/synthetic-source.sqlite" \
  --backup-sqlite "$work/synthetic-backup.sqlite" \
  --destination-url-env IMPORT_DESTINATION_URL \
  --owner-map "$work/owners.json" \
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

## Verification commands

```bash
uv run pytest -q backend/tests/test_import_legacy_sqlite.py
uv run pytest -q backend/tests/postgres/test_import_legacy_sqlite.py
./scripts/check.sh
```

Without `TEST_DATABASE_ADMIN_URL`, source-only tests still run and the script warns that PostgreSQL importer validation was skipped. CI provides PostgreSQL 17 and requires every PostgreSQL test to execute with zero skips.
