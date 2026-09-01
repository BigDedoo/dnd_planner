# Temporary legacy profile recovery

This feature supports the one-time Clerk Development to Clerk Production
identity transition. It lets an authenticated, unlinked Account claim a User
that has been explicitly inserted into `legacy_profile_recoveries` by the
separate migration-data preparation step.

Set `LEGACY_PROFILE_RECOVERY_ENABLED=true` only for the controlled recovery
window. The default is `false`; disabling it hides both recovery endpoints and
leaves normal new-user onboarding unchanged. Enabling it never infers eligible
profiles and does not populate the table.

After the migration window, disable the flag. The removable temporary pieces
are the `legacy_profile_recoveries` table/model, `backend.legacy_profile_recovery`,
the two onboarding recovery endpoints, and the recovery choice in the onboarding
page. Historical Account and AccountIdentity rows are intentionally retained.

## Preparing explicit entries

After the legacy importer has populated an explicitly selected PostgreSQL
destination, use the same source snapshot and normalization policy to derive
only those deterministic legacy User IDs:

```bash
uv run python -m backend.cli.prepare_legacy_profile_recoveries \
  --source-sqlite /absolute/path/to/source.sqlite \
  --normalization-policy /absolute/path/to/normalization-policy.json \
  --destination-url-env RECOVERY_DESTINATION_URL \
  --dry-run

uv run python -m backend.cli.prepare_legacy_profile_recoveries \
  --source-sqlite /absolute/path/to/source.sqlite \
  --normalization-policy /absolute/path/to/normalization-policy.json \
  --destination-url-env RECOVERY_DESTINATION_URL \
  --apply
```

The command validates every source-derived deterministic UUID against an
existing destination User before writing anything. It does not inspect or
change `User.account_id`, does not claim profiles, and is idempotent. The
destination URL has no default and must be supplied through the exact named
environment variable.

## Reconciling the approved availability snapshot

The temporary availability reconciliation command exists only for the audited
Raspberry snapshot merge. It reuses the importer's normalization policy and
deterministic user mapping, requires the explicit approved source checksum, and
changes only availability belonging to the twelve canonical legacy users. It
inserts missing rows, updates conflicting statuses to the snapshot value, and
never deletes rows.

Run the count-only safety check first:

```bash
uv run python -m backend.cli.reconcile_legacy_availability \
  --source-sqlite /absolute/path/to/source.sqlite \
  --normalization-policy /absolute/path/to/normalization-policy.json \
  --expected-source-sha256 <approved-sha256> \
  --destination-url-env RECONCILIATION_DESTINATION_URL \
  --dry-run
```

Apply only when the dry-run counts match the separately approved operation:

```bash
uv run python -m backend.cli.reconcile_legacy_availability \
  --source-sqlite /absolute/path/to/source.sqlite \
  --normalization-policy /absolute/path/to/normalization-policy.json \
  --expected-source-sha256 <approved-sha256> \
  --destination-url-env RECONCILIATION_DESTINATION_URL \
  --expect-insert <approved-insert-count> \
  --expect-update <approved-update-count> \
  --expect-unchanged <approved-unchanged-count> \
  --apply
```

The command fails closed unless the normalized source contains exactly 12
users, 3 groups, 16 memberships, and 1,724 availability rows. It also refuses
missing or mismatched deterministic users, duplicate source keys, unresolved
normalization conflicts, and production-only availability keys belonging to a
legacy user. Apply also refuses to write unless its locked destination counts
match all three explicit approved count arguments. Rerun `--dry-run` after
apply to prove idempotency.
