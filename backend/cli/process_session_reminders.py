"""Send due personal reminders, or inspect eligibility without sending/writing."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from backend.config import Settings
from backend.db import create_required_database_runtime, validate_database_readiness
from backend.email_delivery import ReminderEmail, SmtpReminderSender
from backend.notifications import process_session_reminders


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument(
        "--check-smtp", action="store_true", help="TLS/auth only; sends no email"
    )
    mode.add_argument(
        "--send-test-to-support",
        action="store_true",
        help="Send one controlled test only to support@dedoo.fr",
    )
    args = parser.parse_args(argv)
    runtime = None
    try:
        settings = Settings()
        if not args.dry_run and not settings.email_delivery_enabled:
            print("email_delivery=disabled sent=0")
            return 1 if args.check_smtp or args.send_test_to_support else 0
        sender = None if args.dry_run else SmtpReminderSender(settings)
        if args.check_smtp:
            sender.check_connection()
            print("smtp_tls_auth=ok sent=0")
            return 0
        if args.send_test_to_support:
            sender.send(
                ReminderEmail(
                    "support@dedoo.fr",
                    "DnD Planner reminder delivery test",
                    "Controlled transactional reminder delivery test. No user/session data is included.",
                )
            )
            print("smtp_test=accepted sent=1")
            return 0
        runtime = create_required_database_runtime(settings.database_url)
        validate_database_readiness(runtime)
        with runtime.session_factory() as session:
            counts = process_session_reminders(
                session,
                now_utc=datetime.now(timezone.utc),
                dry_run=args.dry_run,
                sender=sender,
                clock=lambda: datetime.now(timezone.utc),
            )
        print(
            " ".join(f"{key}={value}" for key, value in counts.items())
            + f" dry_run={str(args.dry_run).lower()}"
        )
        return 1 if counts["failed"] else 0
    except Exception:
        # Never print exception strings/tracebacks: SMTP and SQL errors may
        # contain addresses, authentication replies or credentials.
        print("reminder_worker=failed; check configuration, database and mail service")
        return 1
    finally:
        if runtime is not None:
            runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
