"""Operator CLI command to link an authenticated Account to an existing DnD User."""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db import create_database_runtime
from backend.models import Account, User


class LinkAccountError(Exception):
    """Raised when an account cannot be linked to a user."""


def link_account_to_user(
    session: Session,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    dry_run: bool = False,
) -> tuple[Account, User]:
    account = session.get(Account, account_id)
    if not account:
        raise LinkAccountError(f"Account with ID {account_id} does not exist")

    user = session.get(User, user_id)
    if not user:
        raise LinkAccountError(f"User with ID {user_id} does not exist")

    # If already linked to each other -> idempotent success
    if user.account_id == account.id:
        return account, user

    # If user is linked to a different account -> error
    if user.account_id is not None:
        raise LinkAccountError(
            f"User '{user.display_name}' ({user.id}) is already linked to "
            f"a different Account ({user.account_id})"
        )

    # If account is linked to a different user -> error
    existing_user_for_account = session.scalars(
        select(User).where(User.account_id == account.id)
    ).first()
    if existing_user_for_account:
        raise LinkAccountError(
            f"Account '{account.display_name or account.email or account.id}' is "
            f"already linked to a different User '{existing_user_for_account.display_name}' "
            f"({existing_user_for_account.id})"
        )

    if not dry_run:
        user.account_id = account.id
        session.commit()

    return account, user


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicitly link an authenticated Account to an existing DnD User."
    )
    parser.add_argument(
        "--account-id",
        required=True,
        type=uuid.UUID,
        help="UUID of the internal Account (from accounts table / Clerk)",
    )
    parser.add_argument(
        "--user-id",
        required=True,
        type=uuid.UUID,
        help="UUID of the existing DnD User (from users table)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be linked without applying changes",
    )
    args = parser.parse_args()

    if not settings.database_url:
        print("ERROR: DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    runtime = create_database_runtime(settings.database_url)
    session = runtime.open_session()
    try:
        account, user = link_account_to_user(
            session=session,
            account_id=args.account_id,
            user_id=args.user_id,
            dry_run=args.dry_run,
        )
        mode_str = "[DRY RUN] " if args.dry_run else ""
        print(f"{mode_str}Successfully linked:")
        print(
            f"  Account: {account.id} (Email: {account.email}, Name: {account.display_name})"
        )
        print(
            f"  User:    {user.id} (Name: {user.display_name}, Timezone: {user.timezone})"
        )
        return 0
    except LinkAccountError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"UNEXPECTED ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        session.close()
        runtime.dispose()


if __name__ == "__main__":
    sys.exit(main())
