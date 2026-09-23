# Important session emails

Scheduling, meaningfully changing (title, start time or duration), and
cancelling a session queue emails to current linked group members other than
the actor. Notes-only and idempotent edits queue nothing. The global Account →
Notifications switch defaults to On and controls all three; it is independent
of the personal reminder choice and RSVP. Recipient eligibility and current
`Account.email` are checked again at send time.

The migration creates an **empty** `session_event_email_outbox`; historical
`session_notification_deliveries` are logging-only and are never replayed.
Session mutations insert outbox rows in their own PostgreSQL transaction and
never contact SMTP. Successful SMTP acceptance creates a new email-specific
delivery record and removes the pending row in one commit. Failed sends retry
after 1, 5, 15, then at most 60 minutes. A crash after SMTP acceptance but
before DB commit can cause a duplicate on retry (at-least-once delivery).

The existing SMTP configuration and sender are reused; no new secret is needed.
Install only `deploy/systemd/dnd-planner-session-emails.service` and `.timer`
from the merged release after deployment. The timer runs each minute alongside
the unchanged five-minute personal-reminder timer. Inspect safely with:

```bash
systemctl status dnd-planner-session-emails.timer
systemctl list-timers dnd-planner-session-emails.timer
journalctl -u dnd-planner-session-emails.service --since today
sudo docker exec deploy-backend-1 python -m backend.cli.process_session_event_emails --dry-run
```

The dry run sends nothing and writes nothing. Worker logs contain aggregate
counts only, never addresses, message bodies or SMTP diagnostics.
