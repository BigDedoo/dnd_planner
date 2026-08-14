# DnD Planner production cutover runbook

This runbook covers the future production data cutover after the preparation
pull request is merged. It does not authorize public exposure, Phase 2, or use
of the August rehearsal snapshot as production input.

## Safety invariants

- The application stays private until authentication and authorization exist.
- PostgreSQL remains published only on VPS loopback at `127.0.0.1:5432`.
- Next.js remains published only on VPS loopback at `127.0.0.1:3000`.
- FastAPI has no host-published port. Browser API calls continue through
  Next.js `/api/*` rewrites to `http://backend:8000` on the private network.
- `MUTATIONS_ENABLED=false` until the explicit write-enable checkpoint.
- Every deployment uses an exact merged Git SHA; never deploy a dirty tree or
  automatically pull a moving branch.
- Never run `docker compose down -v` for PostgreSQL.
- Never expose ports 80, 443, 3000, 5432, or 8000 publicly during this phase.

## A. Preparation

1. Confirm this preparation PR is merged into `master`, CI is green, and the
   exact merged SHA is recorded.
2. Confirm `/opt/apps/dnd-planner/source` is clean and checked out at that SHA.
3. Confirm PostgreSQL is healthy, uses the preserved
   `postgres_postgres_data` volume, and is bound only to `127.0.0.1:5432`.
4. Confirm `dnd_planner` is at Alembic revision
   `0001_phase_1_domain_schema` and all four domain tables are empty.
5. Confirm the `dnd_planner_migrator` and least-privilege `dnd_planner_app`
   roles, private external bridge `dnd_planner_internal` network, and mode-0600
   VPS environment files exist. The network must not use Docker's `--internal`
   flag because the operator must reach the loopback-published frontend from
   the VPS or an SSH tunnel.
6. Build immutable backend/frontend image tags from the merged SHA and record
   their image IDs.
7. Run the complete repository gate and private disposable deployment smoke.
8. Create a PostgreSQL custom-format backup and perform a disposable restore
   verification.
9. Configure encrypted off-site PostgreSQL backup storage and complete at least
   one tested restore from it. A same-VPS dump or provider VM backup is not a
   substitute for a tested database-level off-site backup.
10. Choose and announce a maintenance window and identify the operator who may
    approve inspect/plan evidence.

## B. Maintenance window

1. Confirm the Raspberry application is still authoritative before the freeze.
2. Stop all Raspberry application writes. Record the freeze time.
3. Verify no user can continue changing availability on the Raspberry.
4. Keep `MUTATIONS_ENABLED=false` on the VPS.
5. Do not start the production application against the empty database.

## C. Final SQLite snapshot

1. Obtain a **fresh** consistent SQLite snapshot from the frozen active
   Raspberry instance using SQLite-supported backup/snapshot mechanics.
2. Do not reuse the August rehearsal snapshot unless the operator independently
   proves no source data changed after it was taken.
3. Store the fresh snapshot in a private timestamped workspace outside Git.
4. Record size, UTC mtime, streaming SHA-256, and `PRAGMA quick_check`.
5. Require `quick_check=ok` and create a distinct read-only private backup with
   the same SHA-256.
6. Never inspect or import directly from the Raspberry or from an unverified
   guessed database path.

## D. Inspect / plan

Use the committed importer against the private source copy. Preserve separate
raw and normalized evidence.

Approved normalization policy:

```text
Admin     -> ignored
Red flags -> 1D6
Jiken     -> Quentin
Nuxio     -> Arnaud
```

Approved precedence:

```text
1D6     > Red flags
Quentin > Jiken
Arnaud  > Nuxio
```

Approved owners:

```text
Green flag -> Dembe
1D6        -> Dembe
Underdark  -> Arnaud
```

1. Run `inspect` with the approved normalization policy.
2. Compare fresh raw statistics, conflicts, alias decisions, canonical counts,
   status counts, and checksums with operator expectations. Rehearsal values are
   an oracle, not values to force.
3. Stop if the fresh snapshot materially differs until the operator reviews it.
4. Run `plan` against empty `dnd_planner` with the migrator URL supplied only
   through the validated environment-variable mechanism.
5. Require zero plan writes, exact source/backup hashes, exact Alembic head,
   empty destination, 12 users, 3 groups, 16 memberships, zero unresolved
   conflicts, and operator-approved availability counts from the fresh source.
6. Have the operator approve the mapping, plan, policy/owner evidence, and all
   checksums before apply.

## E. PostgreSQL apply

1. Reconfirm the freeze and final snapshot hash.
2. Create a pre-apply custom-format backup of empty `dnd_planner` and verify the
   archive/checksum.
3. Run the committed importer `apply --apply` as
   `dnd_planner_migrator`, using the approved plan/mapping and fresh source and
   backup files.
4. Do not disable serializable transaction, advisory-lock, artifact, empty
   destination, source-integrity, or Alembic checks.
5. Require a successful all-or-nothing commit.

## F. Verify

1. Run committed independent `verify` in a fresh transaction.
2. Require exact users, groups, memberships, owners, ordering, availability,
   timestamps, per-user facts, logical checksums, and compatibility projections.
3. Run the exact approved apply again and require `already_applied`, exit zero,
   zero writes, unchanged timestamps, and another exact verify.
4. Stop on any unexplained mismatch. Do not enable application writes.

## G. Read-only application smoke

1. Set the production runtime to `MUTATIONS_ENABLED=false`.
2. Start the exact-SHA backend/frontend images against `dnd_planner`.
3. Through VPS localhost or an SSH tunnel, verify `/`, `/api/test-health`,
   `/api/groups`, representative non-empty `/api/availability/*` reads, and an
   inclusive admin projection. Do not POST.
4. Confirm no public port is reachable. Private operator access is conceptually:

   ```text
   workstation localhost -> SSH -> VPS 127.0.0.1:3000
   ```

5. Stop and investigate on any startup, revision, compatibility, proxy, or data
   mismatch.

## H. Enable writes

This is the irreversible consistency boundary for simple rollback.

1. Obtain explicit operator approval of import verification and read-only smoke.
2. Record that the Raspberry remains frozen and is no longer authoritative.
3. Change only the private VPS runtime setting to `MUTATIONS_ENABLED=true` and
   recreate/restart the backend with the same immutable image.
4. Confirm the setting and perform one approved write/read verification.
5. Record the timestamp of the **first real PostgreSQL application write**.

## I. Post-cutover verification

1. Verify health, groups, representative month reads, and the approved write.
2. Verify database counts/checksums and application logs without exposing
   credentials.
3. Create and checksum a post-cutover custom-format PostgreSQL backup.
4. Verify the off-site backup pipeline receives the encrypted backup and perform
   the scheduled restore test.
5. Keep access private through SSH. Public HTTPS/DNS/reverse-proxy activation is
   a separate authorization after adequate access control exists.

## J. Rollback / forward-fix

> **Before the first new real PostgreSQL application write:** rollback may stop
> the VPS application, leave or restart the frozen Raspberry legacy application,
> abandon the PostgreSQL attempt, investigate, and retry later.

> **After the first new real PostgreSQL application write:** switching users back
> to Raspberry SQLite is not a safe rollback. PostgreSQL may contain facts absent
> from SQLite. Keep PostgreSQL authoritative and use a forward-fix, or execute an
> explicitly designed and operator-approved reconciliation procedure.

Never overwrite `dnd_planner` with a restore during diagnosis. Restore tests
must always target generated `dnd_planner_restore_validation_*` databases.
