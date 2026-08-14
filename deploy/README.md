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

The restore verifier always creates and removes a generated
`dnd_planner_restore_validation_*` database. It never restores over
`dnd_planner`.
