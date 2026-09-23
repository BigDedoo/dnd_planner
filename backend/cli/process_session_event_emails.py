"""Send pending important session emails, or safely inspect due work."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from backend.config import Settings
from backend.db import create_required_database_runtime, validate_database_readiness
from backend.email_delivery import SmtpReminderSender
from backend.session_event_emails import process_session_event_emails


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="No SMTP or database writes"
    )
    args = parser.parse_args(argv)
    runtime = None
    try:
        settings = Settings()
        if not args.dry_run and not settings.email_delivery_enabled:
            print("email_delivery=disabled sent=0")
            return 1
        sender = None if args.dry_run else SmtpReminderSender(settings)
        runtime = create_required_database_runtime(settings.database_url)
        validate_database_readiness(runtime)
        with runtime.session_factory() as session:
            counts = process_session_event_emails(
                session,
                now_utc=datetime.now(timezone.utc),
                dry_run=args.dry_run,
                sender=sender,
            )
        print(
            " ".join(f"{key}={value}" for key, value in counts.items())
            + f" dry_run={str(args.dry_run).lower()}"
        )
        return 1 if counts["failed"] else 0
    except Exception:
        # Provider and database exceptions may contain private content.
        print("session_email_worker=failed; check database and mail service")
        return 1
    finally:
        if runtime is not None:
            runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
