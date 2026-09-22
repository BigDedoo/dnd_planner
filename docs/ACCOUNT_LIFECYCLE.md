# Account privacy and departure

## User-facing access

`/privacy` and `/support` are public. Authenticated users open **Account / Data**
from the account icon beside the avatar. **Download my data** requests
`GET /api/me/export` (also available at `/me/export`) with the existing Clerk
authentication. The JSON attachment includes their application account, optional
profile, memberships/nicknames, availability, RSVPs with session context, created
invite metadata (never hashes/codes), and notification records. It does not
include other people's account data, rosters, availability, auth subjects or
tokens. The export queries do not mutate data; normal account authentication and
profile synchronization still use the existing auth dependency.

Unlinked accounts can use `/account` without creating a planner profile. Linked
accounts load ownership from `/api/me/groups`; a failed group load never presents
an owner-free deletion state. Owners must transfer ownership or delete every
owned group using Group Settings. The deletion-request link leads to Support.
It does not execute deletion or submit a request automatically.

## Required support configuration before public beta

**SUPPORT_CONTACT_URL must be configured before public beta.** Set the operator's
real `mailto:` or `https:` contact in the frontend runtime environment (production
`runtime.frontend.env`, local `frontend/.env.local`). Do not use a `NEXT_PUBLIC_`
variable. The Support server page reads it at request time; it is not a build
argument or an environment object sent to browser JavaScript. The rendered
contact link is necessarily public. Missing/invalid values show “Support contact
is not configured yet” and do not break builds. Executable schemes and HTTPS
URL credentials are rejected.

The deployment script's frontend variable allowlist now permits this one new
variable. Installing that reviewed script and setting the real contact value
are separate release/operator actions; this implementation does neither.
Compose already passes `runtime.frontend.env` to the frontend container.

## Operator-assisted deletion

1. Independently verify the request is from the account holder. An Account UUID
   alone is not proof of ownership. Never ask for passwords or session tokens.
2. Obtain the exact internal Account UUID from the requester/account record.
   Record the verified request and the corresponding Clerk identity in a secure,
   access-controlled operator record before removing the local account. Keep the
   minimum request evidence needed to finish provider removal and reconcile a
   future restore; do not place it in Git or public logs.
3. Use the approved target's `DATABASE_URL` and an operator role authorized for
   the operation. The CLI requires valid PostgreSQL configuration and the current
   schema. It does not create/alter schema or fall back to SQLite.
4. Run the safe default (or explicit `--dry-run`):

   ```bash
   uv run python -m backend.cli.delete_account_data --account-id <ACCOUNT_UUID> --dry-run
   ```

5. Review the UUIDs, counts, owner blocker and tombstone decision. Dry-run changes
   no rows. A missing account, schema/dependency mismatch or database failure
   fails closed. Owners receive: **Transfer ownership or delete owned groups
   first.** Resolve nothing automatically; the account holder uses normal group
   functionality. The CLI does not infer a successor.
6. Only after review and authorization, run:

   ```bash
   uv run python -m backend.cli.delete_account_data --account-id <ACCOUNT_UUID> --apply
   ```

7. Confirm the successful aggregate summary. Availability, memberships/nicknames,
   own RSVPs, recipient notification rows, invites created by the user, and
   associated obsolete recovery links are removed. Shared groups and sessions
   remain. If session creation/cancellation references the user, its UUID remains
   solely as a tombstone: account/auth links and email cleared, name `Deleted
   user`, timezone `UTC`. Otherwise the User row is deleted. Account and
   AccountIdentity rows are removed. All changes commit together or roll back;
   dependency or transaction errors are redacted. Repeating deletion of an absent
   Account returns a safe missing-account error and changes nothing.
8. Handle the corresponding Clerk identity/account separately through the
   approved Clerk account-management process. This CLI never calls Clerk and
   local deletion does not delete a Clerk user or revoke their provider session.
   Until that separate step completes, signing in again can provision a new,
   unlinked internal account. Coordinate the steps and avoid concurrent use while
   processing departure. Do not auto-match or reconnect the tombstone.
9. Tell the user when both application and provider processing are complete.

Shared session titles/notes are retained and are not automatically searched for
personal names. Review any specific text-removal request separately with the
operator; do not promise that free text is automatically anonymized. Server logs
and support correspondence are also outside this database command.

## Backups and restores

Per [the backup runbook](OFFSITE_BACKUPS.md), routine VPS daily sets are retained
for **14 days**, and Raspberry off-site copies for **90 days**. Active-service
deletion happens first; these copies expire normally. Do not manually edit
individual historical backup archives or promise immediate physical erasure.

Deployment backups are explicitly outside routine daily pruning and have no
automatic maximum retention documented here. Review their retention separately;
do not imply that every backup expires after 90 days.

After any disaster restore predating a completed deletion, use the secure
operator request record to re-apply completed deletions before calling the
service fully reconciled. Check ownership blockers on the restored state and
resolve them deliberately before applying. This reconciliation is manual and
is not automated by the restore or backup tools.
