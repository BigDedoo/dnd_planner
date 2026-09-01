# Production deployment artifacts

These files prepare the Phase 1 modular monolith for private-only operation on
the existing VPS. They do not perform the real SQLite cutover.

The application stack contains FastAPI and Next.js. PostgreSQL remains in its
separate `/opt/apps/postgres` Compose project, and all three services share the
external private bridge network `dnd_planner_internal`. Create that network as
a normal bridge, not with Docker's `--internal` flag: an internal network also
blocks the VPS from reaching the frontend's loopback-published port. Privacy is
enforced by the explicit `127.0.0.1:3000` binding, the absence of a FastAPI
host port, PostgreSQL's loopback binding, and the host firewall.

Build and validate an exact Git commit from the repository root:

```bash
export DND_PLANNER_IMAGE_TAG="$(git rev-parse HEAD)"
export DND_PLANNER_ENV_FILE=/opt/apps/dnd-planner/runtime.env
docker compose -f deploy/compose.production.yaml config
docker compose -f deploy/compose.production.yaml build --pull
```

`runtime.env.example` documents the runtime contract only. A populated file
belongs on the VPS at `/opt/apps/dnd-planner/runtime.env` with mode `0600`; it
must never enter Git. `MUTATIONS_ENABLED` remains `false` until the cutover
runbook's explicit write-enable checkpoint.

Create a custom-format logical backup and test its restoration with:

```bash
sudo deploy/backup_postgres.sh dnd_planner
sudo deploy/restore_verify_postgres.sh /opt/apps/dnd-planner/backups/<dump>.dump
```

Daily production backups and the restricted Raspberry Pi off-site pull are
documented in [the off-site backup runbook](../docs/OFFSITE_BACKUPS.md). They
reuse `backup_postgres.sh`, keep routine artifacts separate from deployment
backups, and do not require replacing the application containers.

The restore verifier always creates and removes a generated
`dnd_planner_restore_validation_*` database. It never restores over
`dnd_planner`.

## Routine production deployment

After a change has been merged to `master`, deploy the exact current
`origin/master` commit with one command:

```bash
ssh dnd-vps "sudo dnd-deploy"
```

The command serializes deployments with a host lock, fast-forwards the VPS
checkout to `origin/master`, and exits without rebuilding when that exact SHA
is already deployed. For a new release it builds SHA-tagged backend and
frontend images before touching production, verifies the current private
bindings and service health, creates and checksums a PostgreSQL backup, runs
Alembic with the dedicated migrator role, and replaces only the application
services. It records the release only after local API, container, PostgreSQL,
Caddy, and public HTTPS checks pass.

The deployment preflight requires Clerk Production keys (`sk_live_` for both
backend and frontend, and `pk_live_` for the frontend), requires the two secret
keys to match, and requires `CLERK_AUTHORIZED_PARTIES` to be exactly
`["https://dnd-planner.dedoo.fr"]`. Secret values remain only in the root-owned
runtime files and are never printed.

If post-replacement health fails without a schema change, the command restores
the retained previous application images. If Alembic changed the schema, it
never downgrades or restores the database automatically and instead stops with
a manual-intervention report containing the release SHAs, backup path, and
before/after revisions. Production secrets are read only from the existing
root-owned files and are never printed.
