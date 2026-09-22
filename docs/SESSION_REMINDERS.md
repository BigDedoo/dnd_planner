# Personal session reminders

Account → Notifications offers Off, 1 hour, 3 hours, 12 hours, 1 day (default),
3 days or 7 days before a timed session. The preference is global per DnD user;
personal JSON export schema 2 includes it. The API's GET/PATCH
`/api/me/notification-preferences` (also `/me/...`) requires a linked profile.

Only `upcoming_session_reminder` is emailed. Session events remain logging-only;
missing-RSVP emails are deliberately inactive. No historical delivery rows are
dispatched. Recipients come from current linked `Account.email`, never legacy
profile addresses. Off, declined, cancelled, untimed, invalid-time, non-member,
missing-email and already-started cases are skipped.

Due time is canonical session UTC start minus the user's lead. Catch-up runs
may send after due time but never at/after start. The bounded query covers at
most seven future days plus local-date timezone margins. Successful delivery
keys include kind, session, user, UTC start and lead; title/notes edits do not
duplicate reminders. Rescheduling or changing lead may produce a new reminder.

## Configuration and activation

`EMAIL_DELIVERY_ENABLED=false` is the safe default. Required enabled settings:
`SMTP_HOST`, `SMTP_PORT`, `SMTP_STARTTLS`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`. See `deploy/runtime.env.example`.
The OVH mailbox uses authenticated STARTTLS at `smtp.mail.ovh.net:587`, with
`support@dedoo.fr` as sender and Reply-To. TLS certificates are verified;
network operations time out after 15 seconds. One recipient per message.

An operator must securely supply the mailbox password in the root-owned 0600
`/opt/apps/dnd-planner/runtime.env`; never paste it in commands, logs or Git.
Do not enable delivery or deploy a half-enabled configuration without it.
After normal deployment/migration, verify the connection without sending:

```bash
sudo docker exec deploy-backend-1 python -m backend.cli.process_session_reminders --check-smtp
sudo docker exec deploy-backend-1 python -m backend.cli.process_session_reminders --dry-run
```

The dry run sends nothing and writes no delivery records (works while disabled).
`--send-test-to-support` sends exactly one clearly labelled test to support,
not users; run only with explicit operator authorization, not periodically.

Install **only** the exact merged `deploy/systemd/dnd-planner-reminders.service`
and `.timer` into `/etc/systemd/system`, root:root 0644, after healthy deployment
and SMTP/dry-run verification. Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dnd-planner-reminders.timer
systemctl is-enabled dnd-planner-reminders.timer
systemctl is-active dnd-planner-reminders.timer
systemctl list-timers dnd-planner-reminders.timer
sudo journalctl -u dnd-planner-reminders.service --since today
```

The persistent timer runs every five minutes in the running backend container.
Host `flock` prevents overlap; the in-container timeout kills the worker before
the outer service deadline releases the lock. An unavailable container or mail
server fails visibly and the next run retries. Do not launch an unlocked manual
real-delivery worker alongside the timer. Manual dry runs are safe.

Logs contain aggregate counts, not recipients, passwords or message bodies.
SMTP failures do not record success. Each accepted email is committed separately.
A crash **after SMTP acceptance but before DB commit** can cause a duplicate on
retry: this is at-least-once, not exactly-once delivery. Database uniqueness is
the final dedupe guard; this is not a distributed queue. Session/RSVP mutations
never contact SMTP. Existing backup/offsite timers are independent and unchanged.
