"""Reconcile one validated legacy availability snapshot into PostgreSQL."""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.cli import import_legacy_sqlite as importer
from backend.db import create_database_runtime, validate_database_readiness
from backend.legacy_contract import GROUPS, LEGACY_USERS, deterministic_legacy_uuid
from backend.models import Availability, AvailabilityStatus, User

EXPECTED_USER_COUNT = 12
EXPECTED_GROUP_COUNT = 3
EXPECTED_MEMBERSHIP_COUNT = 16
EXPECTED_AVAILABILITY_COUNT = 1724
DESTINATION_ENV_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class AvailabilityReconciliationError(RuntimeError):
    """The selected source or destination cannot be reconciled safely."""


@dataclass(frozen=True)
class ExpectedAvailability:
    user_id: uuid.UUID
    user_name: str
    day: date
    status: AvailabilityStatus


@dataclass(frozen=True)
class AvailabilityReconciliationResult:
    insert_count: int
    update_count: int
    unchanged_count: int
    delete_count: int
    verified_count: int


@dataclass(frozen=True)
class RequiredReconciliationCounts:
    insert_count: int
    update_count: int
    unchanged_count: int


def load_expected_availability(
    source_sqlite: Path,
    normalization_policy_path: Path | None,
    expected_source_sha256: str,
) -> tuple[ExpectedAvailability, ...]:
    """Load the exact normalized legacy subset through the approved importer."""
    expected_hash = importer._validate_expected_sha256(expected_source_sha256)
    policy = (
        importer._load_normalization_policy(normalization_policy_path)
        if normalization_policy_path is not None
        else None
    )
    inspection = importer.inspect_source(source_sqlite, policy)
    importer._raise_for_source_problems(inspection)
    if inspection["metadata_after"]["sha256"] != expected_hash:
        raise AvailabilityReconciliationError(
            "Selected source does not match expected SHA-256"
        )

    normalization = inspection.get("normalization")
    if normalization is None:
        raise AvailabilityReconciliationError(
            "An explicit normalization policy is required"
        )
    if normalization.get("remaining_unresolved_conflict_count"):
        raise AvailabilityReconciliationError(
            "Source normalization has unresolved conflicts"
        )

    logical_facts = list(inspection["logical_facts"])
    source_users = {str(fact["user_name"]) for fact in logical_facts}
    expected_users = set(LEGACY_USERS)
    membership_count = sum(len(members) for members in GROUPS.values())
    if (
        len(LEGACY_USERS) != EXPECTED_USER_COUNT
        or source_users != expected_users
        or set(normalization.get("canonical_users", ())) != expected_users
        or set(normalization.get("canonical_groups", ())) != set(GROUPS)
        or len(GROUPS) != EXPECTED_GROUP_COUNT
        or membership_count != EXPECTED_MEMBERSHIP_COUNT
        or len(logical_facts) != EXPECTED_AVAILABILITY_COUNT
    ):
        raise AvailabilityReconciliationError(
            "Normalized source does not match the approved legacy counts"
        )

    user_ids = {
        user_name: deterministic_legacy_uuid("user", user_name)
        for user_name in LEGACY_USERS
    }
    if len(set(user_ids.values())) != EXPECTED_USER_COUNT:
        raise AvailabilityReconciliationError(
            "Deterministic legacy user mapping is ambiguous"
        )

    expected_rows = tuple(
        ExpectedAvailability(
            user_id=user_ids[str(fact["user_name"])],
            user_name=str(fact["user_name"]),
            day=date.fromisoformat(str(fact["day"])),
            status=AvailabilityStatus(str(fact["status"])),
        )
        for fact in logical_facts
    )
    keys = [(row.user_id, row.day) for row in expected_rows]
    if len(keys) != len(set(keys)):
        raise AvailabilityReconciliationError(
            "Normalized source contains duplicate availability keys"
        )
    return expected_rows


def reconcile_availability(
    session: Session,
    expected_rows: Sequence[ExpectedAvailability],
    *,
    apply: bool,
    required_counts: RequiredReconciliationCounts | None = None,
) -> AvailabilityReconciliationResult:
    """Classify and optionally reconcile only the selected legacy availability."""
    if not expected_rows:
        raise AvailabilityReconciliationError(
            "At least one expected availability row is required"
        )
    expected_by_key = {(row.user_id, row.day): row for row in expected_rows}
    if len(expected_by_key) != len(expected_rows):
        raise AvailabilityReconciliationError(
            "Expected availability contains duplicate keys"
        )

    user_names: dict[uuid.UUID, str] = {}
    for row in expected_rows:
        previous = user_names.setdefault(row.user_id, row.user_name)
        if previous != row.user_name:
            raise AvailabilityReconciliationError(
                "Deterministic user mapping resolves to multiple source names"
            )
    user_ids = tuple(user_names)

    try:
        user_statement = sa.select(User).where(User.id.in_(user_ids))
        availability_statement = sa.select(Availability).where(
            Availability.user_id.in_(user_ids)
        )
        if apply:
            user_statement = user_statement.with_for_update()
            availability_statement = availability_statement.with_for_update()

        destination_users = session.scalars(user_statement).all()
        users_by_id = {user.id: user for user in destination_users}
        if set(users_by_id) != set(user_ids):
            raise AvailabilityReconciliationError(
                "One or more deterministic legacy users are missing"
            )
        if any(
            users_by_id[user_id].display_name != source_name
            for user_id, source_name in user_names.items()
        ):
            raise AvailabilityReconciliationError(
                "A deterministic destination user conflicts with its source identity"
            )

        destination_rows = session.scalars(availability_statement).all()
        destination_by_key = {(row.user_id, row.day): row for row in destination_rows}
        unexpected_keys = set(destination_by_key) - set(expected_by_key)
        if unexpected_keys:
            raise AvailabilityReconciliationError(
                "Destination has production-only availability for a legacy user"
            )

        missing_keys = set(expected_by_key) - set(destination_by_key)
        update_keys = {
            key
            for key in set(expected_by_key) & set(destination_by_key)
            if destination_by_key[key].status != expected_by_key[key].status
        }
        unchanged_count = len(expected_rows) - len(missing_keys) - len(update_keys)

        if apply:
            actual_counts = RequiredReconciliationCounts(
                insert_count=len(missing_keys),
                update_count=len(update_keys),
                unchanged_count=unchanged_count,
            )
            if required_counts is None:
                raise AvailabilityReconciliationError(
                    "Apply requires explicit approved reconciliation counts"
                )
            if actual_counts != required_counts:
                raise AvailabilityReconciliationError(
                    "Current reconciliation counts differ from approved counts"
                )
            session.add_all(
                Availability(
                    user_id=expected_by_key[key].user_id,
                    day=expected_by_key[key].day,
                    status=expected_by_key[key].status,
                )
                for key in missing_keys
            )
            for key in update_keys:
                destination_by_key[key].status = expected_by_key[key].status
            session.flush()

            verified_rows = session.scalars(availability_statement).all()
            verified_by_key = {(row.user_id, row.day): row for row in verified_rows}
            if set(verified_by_key) != set(expected_by_key) or any(
                verified_by_key[key].status != expected.status
                for key, expected in expected_by_key.items()
            ):
                raise AvailabilityReconciliationError(
                    "Post-write legacy availability verification failed"
                )
            session.commit()
        else:
            session.rollback()

        return AvailabilityReconciliationResult(
            insert_count=len(missing_keys),
            update_count=len(update_keys),
            unchanged_count=unchanged_count,
            delete_count=0,
            verified_count=len(expected_rows),
        )
    except Exception:
        session.rollback()
        raise


def _destination_url(environment_name: str) -> str:
    if DESTINATION_ENV_PATTERN.fullmatch(environment_name) is None:
        raise AvailabilityReconciliationError(
            "Destination environment variable name is invalid"
        )
    value = os.getenv(environment_name)
    if value is None or not value.strip():
        raise AvailabilityReconciliationError(
            f"Destination environment variable {environment_name} is missing or blank"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.reconcile_legacy_availability",
        description=(
            "Reconcile the exact validated legacy availability subset without deletes."
        ),
    )
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--normalization-policy", type=Path, required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--destination-url-env", required=True)
    parser.add_argument("--expect-insert", type=int)
    parser.add_argument("--expect-update", type=int)
    parser.add_argument("--expect-unchanged", type=int)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    runtime = None
    try:
        arguments = build_parser().parse_args(argv)
        expected_rows = load_expected_availability(
            arguments.source_sqlite,
            arguments.normalization_policy,
            arguments.expected_source_sha256,
        )
        runtime = create_database_runtime(
            _destination_url(arguments.destination_url_env)
        )
        validate_database_readiness(runtime)
        required_counts = None
        if arguments.apply:
            expected_cli_counts = (
                arguments.expect_insert,
                arguments.expect_update,
                arguments.expect_unchanged,
            )
            if any(value is None or value < 0 for value in expected_cli_counts):
                raise AvailabilityReconciliationError(
                    "Apply requires nonnegative --expect-insert, --expect-update, "
                    "and --expect-unchanged values"
                )
            required_counts = RequiredReconciliationCounts(*expected_cli_counts)
        with runtime.open_session() as session:
            result = reconcile_availability(
                session,
                expected_rows,
                apply=arguments.apply,
                required_counts=required_counts,
            )
        action = "apply" if arguments.apply else "dry-run"
        print(
            f"{action}: insert={result.insert_count} "
            f"update={result.update_count} "
            f"unchanged={result.unchanged_count} "
            f"delete={result.delete_count} "
            f"verified={result.verified_count}"
        )
        return 0
    except (importer.ImporterError, AvailabilityReconciliationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            "error: unexpected availability reconciliation failure "
            f"({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    finally:
        if runtime is not None:
            runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
