# DnD Planner off-site PostgreSQL backups

Production creates a validated custom-format PostgreSQL archive on the VPS.
The Raspberry Pi later pulls completed daily sets through a dedicated,
read-only SSH key and verifies their SHA-256 before publishing them locally.
The VPS never connects to the Pi.

## Locations and retention

- VPS daily sets: `/opt/apps/dnd-planner/backups/daily`, retained for 14 days.
- Deployment backups: `/opt/apps/dnd-planner/backups`, unaffected by daily
  retention.
- Raspberry archive: `/srv/backups/dnd-planner-postgres`, retained for 90 days.
- Raspberry status: `/srv/backups/dnd-planner-postgres/LAST_SUCCESS`.

Each VPS set contains `<name>.dump`, `<name>.dump.sha256`, and
`<name>.dump.metadata`. Each verified Pi set is stored atomically in a private
directory named `<name>` with those same three files.

## Automation

The VPS installs:

- `dnd-planner-backup.service`
- `dnd-planner-backup.timer` (approximately 01:30 UTC daily)
- `/usr/local/sbin/dnd-planner-routine-backup`

The Pi installs:

- `dnd-planner-offsite-pull.service`
- `dnd-planner-offsite-pull.timer` (approximately 04:15 Europe/Paris daily)
- `/usr/local/sbin/dnd-planner-pull-backups`

The routine wrapper shares `/run/lock/dnd-planner-deploy.lock` with deployment,
reuses `deploy/backup_postgres.sh`, validates its published paths and checksum,
and prunes only complete daily sets after a successful backup. The Pi pull uses
neither rsync `--delete` nor an interactive SSH account. It stages incoming
files privately and publishes a set only after all three files and the checksum
are valid. Pi retention runs only after a successful pull and verification.

## Operations

Inspect timers and recent logs:

```bash
systemctl list-timers dnd-planner-backup.timer
journalctl -u dnd-planner-backup.service --since today

systemctl list-timers dnd-planner-offsite-pull.timer
journalctl -u dnd-planner-offsite-pull.service --since today
```

Run each job manually:

```bash
sudo systemctl start dnd-planner-backup.service
sudo systemctl start dnd-planner-offsite-pull.service
```

Inspect the non-sensitive Pi status marker and verify an archived checksum:

```bash
sudo -u dnd-backup cat /srv/backups/dnd-planner-postgres/LAST_SUCCESS
sudo -u dnd-backup sh -c \
  'cd /srv/backups/dnd-planner-postgres/<set> && sha256sum --check <set>.dump.sha256'
```

Disable scheduling without deleting any backup:

```bash
sudo systemctl disable --now dnd-planner-backup.timer
sudo systemctl disable --now dnd-planner-offsite-pull.timer
```

The VPS key is restricted with OpenSSH `restrict` and a forced
`rrsync -ro /opt/apps/dnd-planner/backups/daily` command. The dedicated account
has no sudo or Docker access and cannot modify the remote archive. The Pi pins
the VPS ED25519 host key and keeps its dedicated private key mode `0600`.

For a separate restore drill, follow the restore verification procedure in
[`deploy/README.md`](../deploy/README.md). Never restore a test archive into the
production `dnd_planner` database.

## Optional Better Stack success heartbeats

Two independent daily heartbeats monitor completion, rather than application
uptime:

| Heartbeat | Job | Expected schedule | Host secret file |
| --- | --- | --- | --- |
| DnD Planner - VPS PostgreSQL Backup | Verified VPS routine backup | 01:30 UTC, plus up to 10 minutes randomized delay | `/etc/dnd-planner/secrets/vps-backup-heartbeat` |
| DnD Planner - Off-site Backup | Verified Pi pull | 04:15 Europe/Paris, plus up to 10 minutes randomized delay | `/etc/dnd-planner/secrets/offsite-backup-heartbeat` |

Both timers retain their existing `Persistent=true` and `AccuracySec=1m`.
Configure the daily Better Stack grace periods to allow for that delay, job
runtime, the VPS deployment-lock wait, and the Pi's timezone/DST changes. A
missing heartbeat triggers Better Stack after its configured grace period;
this code does not change the monitor configuration or send `/fail` signals.

Heartbeat URLs are bearer secrets. Never paste them into a chat, commit them,
add them to examples/CI, print them, or pass them as command-line arguments.
Each host secret file contains exactly one raw HTTPS URL, optionally ending
with one LF. It must be a regular non-symlink file owned by `root:root`, mode
`0600`, in a `root:root` mode `0700` secrets directory. No environment-variable
fallback is used.

The units use `LoadCredential=betterstack_heartbeat:<host secret file>`, available
since systemd 247. Systemd reads the root-only file and gives the service user
access through `$CREDENTIALS_DIRECTORY/betterstack_heartbeat`, preserving the
existing service hardening. See the [systemd credential documentation](https://github.com/systemd/systemd/blob/v259/man/systemd.exec.xml)
and [curl configuration documentation](https://curl.se/docs/manpage.html).

Direct script execution without a credential skips reporting successfully.
The source units name an absolute credential file: **provision the file before
installing/reloading these units**. A missing absolute source file prevents
systemd from starting the job; it is not silently optional at that layer.

`deploy/backup_success_heartbeat.sh` is a shared delivery helper installed beside
both wrappers as `/usr/local/sbin/backup_success_heartbeat.sh`. The wrappers
call it only after success:

- VPS: backup/path/artifact/checksum validation, ownership/permissions, retention.
- Pi: transfer validation, atomic publication, retention, validation and SHA-256
  recheck of the newest complete archive, then successful atomic `LAST_SUCCESS`.

The helper accepts no URL argument, disables tracing, rejects empty/non-regular/
symlink credentials, NULs, embedded CR/LF, whitespace and curl-config injection,
and requires HTTPS. Curl ignores user curlrc files, receives its URL on stdin,
discards response bodies, follows no redirects, and requires HTTP 2xx. Connection
timeout is 3 seconds; each request is limited to 10 seconds, with one retry,
1-second retry delay and a 15-second retry window (at most about 21 seconds).
See [curl's timeout/retry behavior](https://curl.se/docs/manpage.html).

Invalid credentials, a missing helper, client failures or network/HTTP failure
produce only `Warning: backup succeeded but monitoring heartbeat delivery failed`.
The completed valid backup remains successful. A backup/verification/retention/
status-write failure exits before reporting. Existing retention rules, restricted
SSH identity and backup destinations remain unchanged.

## Activation gate and host installation plan

Repository merge is preparation only. Do not install files, reload units, run
jobs, send heartbeats or change timers until the operator explicitly authorizes
host activation. An application deployment is not needed for this integration.

Before activation on **each** host, use its existing trusted SSH route to check:

```bash
systemctl --version
curl --version
```

Require systemd >=247 and curl support for the helper's flags. If either host
is incompatible, stop; do not substitute environment variables or weaken the
units. If the Pi cannot be reached through its known SSH route, the operator
must perform its host steps manually. Do not guess another host or credential.

### Manual secret entry (operator only)

Run this on the VPS, without putting the URL into the command or shell history:

```bash
sudo install -d -o root -g root -m 0700 /etc/dnd-planner/secrets
# Create only if absent; never overwrite an existing credential with /dev/null.
sudo test ! -L /etc/dnd-planner/secrets/vps-backup-heartbeat || exit 1
if ! sudo test -e /etc/dnd-planner/secrets/vps-backup-heartbeat; then
  sudo install -o root -g root -m 0600 /dev/null \
    /etc/dnd-planner/secrets/vps-backup-heartbeat
fi
sudo test -f /etc/dnd-planner/secrets/vps-backup-heartbeat || exit 1
sudoedit /etc/dnd-planner/secrets/vps-backup-heartbeat
sudo chown root:root /etc/dnd-planner/secrets/vps-backup-heartbeat
sudo chmod 0600 /etc/dnd-planner/secrets/vps-backup-heartbeat
```

Enter only the VPS heartbeat URL in the editor; do not include quotes or an
environment assignment. Do not display its contents afterward. Stop on a
symlink or non-regular file rather than editing it.

On the Pi, use the same commands with the credential path replaced by:

```text
/etc/dnd-planner/secrets/offsite-backup-heartbeat
```

Enter the **off-site** heartbeat URL there. Keep the URLs on their respective
hosts and outside the checkout. Confirm only metadata with `sudo stat`, never
`cat` or a verbose curl invocation.

### Install reviewed files, with a rollback copy

Stage files from the exact reviewed merged commit in a private host directory
outside the application checkout. Verify their bytes against that commit. Use
the staged directory as `$stage` in the following commands. Keep a root-only
rollback directory created with `sudo mktemp -d /var/tmp/dnd-heartbeats-rollback.XXXXXXXX`
(mode `0700`), and record its exact path as `$rollback`. Before replacing
anything, preserve the installed wrapper and service with `sudo cp -a` into
that directory; preserve a pre-existing helper too, if one exists. Do not print
credentials while collecting rollback files.

On the VPS, proposed systemctl commands are:

```bash
sudo systemctl stop dnd-planner-backup.timer
systemctl show dnd-planner-backup.service -p ActiveState -p SubState
# Continue only when the service is inactive; wait for a running job, do not kill it.
```

Install these exact files from the reviewed commit:

```bash
bash -n "$stage/deploy/backup_success_heartbeat.sh"
bash -n "$stage/deploy/routine_backup_postgres.sh"
sudo install -o root -g root -m 0644 "$stage/deploy/backup_success_heartbeat.sh" \
  /usr/local/sbin/backup_success_heartbeat.sh
sudo install -o root -g root -m 0755 "$stage/deploy/routine_backup_postgres.sh" \
  /usr/local/sbin/dnd-planner-routine-backup
sudo install -o root -g root -m 0644 "$stage/deploy/systemd/dnd-planner-backup.service" \
  /etc/systemd/system/dnd-planner-backup.service
sudo systemd-analyze verify /etc/systemd/system/dnd-planner-backup.service
sudo systemctl daemon-reload
sudo systemctl start dnd-planner-backup.service
```

On the Pi:

```bash
sudo systemctl stop dnd-planner-offsite-pull.timer
systemctl show dnd-planner-offsite-pull.service -p ActiveState -p SubState
# Continue only when the service is inactive.
bash -n "$stage/deploy/backup_success_heartbeat.sh"
bash -n "$stage/deploy/pull_postgres_backups.sh"
sudo install -o root -g root -m 0644 "$stage/deploy/backup_success_heartbeat.sh" \
  /usr/local/sbin/backup_success_heartbeat.sh
sudo install -o root -g root -m 0755 "$stage/deploy/pull_postgres_backups.sh" \
  /usr/local/sbin/dnd-planner-pull-backups
sudo install -o root -g root -m 0644 "$stage/deploy/systemd/dnd-planner-offsite-pull.service" \
  /etc/systemd/system/dnd-planner-offsite-pull.service
sudo install -d -o root -g root -m 0755 /usr/local/share/doc/dnd-planner
sudo install -o root -g root -m 0644 "$stage/docs/OFFSITE_BACKUPS.md" \
  /usr/local/share/doc/dnd-planner/OFFSITE_BACKUPS.md
sudo systemd-analyze verify /etc/systemd/system/dnd-planner-offsite-pull.service
sudo systemctl daemon-reload
sudo systemctl start dnd-planner-offsite-pull.service
```

Existing scripts were installed executable; verify their ownership/modes in
preflight and preserve them if they differ from these documented defaults.
Neither timer file changes. Preserve their enabled state; these commands stop
them only temporarily during installation.

### Validate one manual run on each host

For the VPS, inspect `Result=success` and `ExecMainStatus=0`, the recent service
journal, the newest complete three-file daily set, mode `0440`/owner `root:dnd-backup`,
and its SHA-256 manifest with `sha256sum --check --strict` in the daily directory.
For the Pi, inspect the same service result, the three-file newest archive,
its checksum, and `LAST_SUCCESS` with a fresh UTC timestamp and matching
filename/digest. Do not restore an archive or inspect its business data.

Check each corresponding Better Stack dashboard heartbeat's latest received
timestamp against the manual job time. Do not paste the URL into reports.
A successful backup plus the generic warning means backup integrity passed
but monitoring did not: investigate connectivity/credential setup, preserving
the backup, before declaring monitoring active. Never use `bash -x` around
operator secret entry, or a curl URL in argv for diagnosis.

After successful job and dashboard verification, restore scheduling:

```bash
# VPS
sudo systemctl start dnd-planner-backup.timer
systemctl is-enabled dnd-planner-backup.timer
systemctl is-active dnd-planner-backup.timer
systemctl list-timers dnd-planner-backup.timer
# Pi
sudo systemctl start dnd-planner-offsite-pull.timer
systemctl is-enabled dnd-planner-offsite-pull.timer
systemctl is-active dnd-planner-offsite-pull.timer
systemctl list-timers dnd-planner-offsite-pull.timer
```

### Monitoring-only rollback

If installation/verification fails, stop the relevant timer and wait for any
running job to finish. Restore the exact saved wrapper and service (and a
pre-existing helper, if any) using `sudo cp -a` from the recorded root-only
rollback directory. If this activation introduced the helper, it may be left
unused or removed by its exact path. Run `sudo systemctl daemon-reload` and
restart the previously active timer. Verify it retains its prior enabled state
and the job uses the old unit with no `LoadCredential` directive. Keep the
rollback copy until verification succeeds; then remove only that validated
temporary directory, never a backup directory.

Credential files may stay root-only and unused for retry; no backup data,
`LAST_SUCCESS`, application containers, database, retention settings, SSH keys,
or timer schedules are changed by this rollback. Better Stack will report a
missing heartbeat until the operator pauses/reconfigures it or reactivates
monitoring.

## Repository checks

```bash
bash -n deploy/backup_success_heartbeat.sh
bash -n deploy/routine_backup_postgres.sh
bash -n deploy/pull_postgres_backups.sh
bash -n deploy/tests/test_backup_heartbeats.sh
bash deploy/tests/test_backup_heartbeats.sh
git diff --check
```

The focused tests run actual wrappers against synthetic files and command
doubles, including credential rejection, tracing/argv/output redaction, HTTP
failure, success ordering, retention failure and corrupted newest archive.
They never send a heartbeat or use Docker, production PostgreSQL or SSH.
