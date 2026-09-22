"""Operator-only application data deletion; never calls Clerk."""

import argparse
import json
import sys
import uuid

from backend.account_data import AccountDeletionError, delete_account_data
from backend.db import create_required_database_runtime, validate_database_readiness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", type=uuid.UUID, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="Read-only preview (default)"
    )
    mode.add_argument(
        "--apply", action="store_true", help="Explicitly delete application data"
    )
    args = parser.parse_args(argv)
    runtime = None
    try:
        # Load inside the safe error boundary so invalid configuration cannot
        # print a validation exception containing a supplied secret.
        from backend.config import Settings

        runtime = create_required_database_runtime(Settings().database_url)
        validate_database_readiness(runtime)
        with runtime.open_session() as session:
            summary = delete_account_data(session, args.account_id, apply=args.apply)
        print(json.dumps(summary, indent=2))
        return 1 if summary["blocker"] else 0
    except AccountDeletionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "ERROR: Database configuration/readiness failed; no deletion performed.",
            file=sys.stderr,
        )
        return 1
    finally:
        if runtime is not None:
            runtime.dispose()


if __name__ == "__main__":
    sys.exit(main())
