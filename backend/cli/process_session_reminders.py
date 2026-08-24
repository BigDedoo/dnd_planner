"""Record due session reminders for a future cron/systemd timer."""

from __future__ import annotations

import argparse
from datetime import date

from backend.config import settings
from backend.db import create_required_database_runtime
from backend.notifications import process_session_reminders


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days-ahead", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.days_ahead <= 90:
        parser.error("--days-ahead must be between 0 and 90")

    runtime = create_required_database_runtime(settings.database_url)
    with runtime.session_factory() as session:
        counts = process_session_reminders(
            session,
            today=date.today(),
            days_ahead=args.days_ahead,
            dry_run=args.dry_run,
        )
    print(
        f"upcoming={counts['upcoming']} missing_rsvp={counts['missing_rsvp']} "
        f"dry_run={str(args.dry_run).lower()}"
    )


if __name__ == "__main__":
    main()
