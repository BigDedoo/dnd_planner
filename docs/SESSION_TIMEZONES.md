# Group session time contract

Session `day` and `start_time` are local wall-clock values in `Group.timezone`.
Duration is elapsed minutes. API-created groups default to `Europe/Paris`;
existing groups and the low-level database default remain unchanged.
Availability and untimed sessions remain date-only.

Owners can edit an IANA timezone in **Group Settings → General**. This changes
the interpretation of existing session times, not their stored dates or clock
times. Non-owners can only view the setting. A change is rejected if any existing
timed session would become ambiguous or nonexistent at a DST transition.
Creating/editing timed sessions rejects those times too; choose another start
time rather than guessing an offset.

`backend/session_time.py` resolves wall times by round-tripping both DST folds.
Timed session responses include derived `starts_at_utc`, `ends_at_utc`, and
`group_timezone`. The end instant is start UTC plus duration. Untimed sessions
have null UTC instants. No new database columns or migration are needed.

Both ICS endpoints use the same conversion and export timed events with UTC
`DTSTART`/`DTEND`. All-day events retain `VALUE=DATE`. Google Calendar uses only
the server UTC instants for timed events and UTC date arithmetic for all-day
boundaries, never the browser timezone. App displays/inputs remain group-local.

Example: Paris, 29 August 2026, 20:00, 180 minutes exports as
`20260829T180000Z/20260829T210000Z`. Paris, 12 December at 20:00 starts at 19:00Z.

The `tzdata` Python dependency ensures minimal images have IANA data. The backend
Docker build checks `Europe/Paris` with the system timezone search path disabled.
No existing groups, sessions, or availability are rewritten during deployment.
