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
