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

If post-replacement health fails without a schema change, the command restores
the retained previous application images. If Alembic changed the schema, it
never downgrades or restores the database automatically and instead stops with
a manual-intervention report containing the release SHAs, backup path, and
before/after revisions. Production secrets are read only from the existing
root-owned files and are never printed.

---

## Phase 2A: Authentication Foundation Architecture

Phase 2A introduces user authentication and stable internal application accounts powered by Clerk.

### Required Environment Variables

Add the following to `/opt/apps/dnd-planner/runtime.env` (and local `.env`):

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`: Clerk instance publishable key (`pk_live_...` or `pk_test_...`)
- `CLERK_SECRET_KEY`: Clerk instance secret key (`sk_live_...` or `sk_test_...`)
- `CLERK_ISSUER` (optional): Explicit Clerk issuer URL (e.g. `https://clerk.yourdomain.com` or `https://<instance>.clerk.accounts.dev`)
- `CLERK_JWKS_URL` (optional): Explicit Clerk JWKS URL override

### High-Level Authentication Flow

1. **Edge & Proxy**: Requests from the internet first pass through Caddy Basic Auth.
2. **Frontend Session**: Next.js loads Clerk SDK (`@clerk/nextjs`), maintaining the user session via cookies and JWT session tokens.
3. **API Proxying**: Next.js rewrites `/api/*` requests to FastAPI upstream (`http://backend:8000/*`).
4. **Backend Token Verification**: FastAPI independently verifies incoming Clerk session JWTs against Clerk's JWKS or public key.
5. **Idempotent Account Resolution**: On first authentication from a previously unseen Clerk subject (`sub`), FastAPI transactionally provisions an `accounts` record and an `account_identities` record. Subsequent requests resolve to the same internal `accounts.id`.
6. **Safe Account Surface**: `GET /api/me` (and `GET /me`) returns safe account details (`id`, `email`, `display_name`). No tokens or secrets are leaked.

### Identity Distinctions & Domain Constraints

- `accounts`: Internal, long-lived application identity. The primary key (`accounts.id`) is the permanent reference for the user.
- `account_identities`: External authentication provider mapping (`provider = 'clerk'`, `provider_subject = <clerk user id>`).
- `users` (Legacy DnD Participants): The 12 existing migrated DnD participants remain completely untouched. No automated linking or claiming occurs in Phase 2A.

### Future Intended Relationships

In Phase 2B (Legacy Claiming):
```text
authenticated account (accounts.id)
       │
       ▼ (Phase 2B explicit claim/linking)
   linked DnD user (users.id)
       │
       ▼
group memberships / availability
```

And in future monetization (Phase 3+):
```text
   accounts.id
       │
       ▼ (Future Billing)
billing / subscription
```

### Important Operational Notes

- **Caddy Basic Auth Kept**: Site-wide Caddy Basic Auth remains strictly enabled during this transition.
- **No Billing / Stripe**: Billing and Stripe integrations are intentionally excluded from Phase 2A.
- **Legacy Account Claiming**: Explicit account claiming for the 12 existing DnD users will be delivered in Phase 2B.
