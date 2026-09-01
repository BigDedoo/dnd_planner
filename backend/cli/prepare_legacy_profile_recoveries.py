"""Prepare explicit recovery rows from one validated legacy SQLite source."""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from backend.cli import import_legacy_sqlite as importer
from backend.db import create_database_runtime, validate_database_readiness
from backend.legacy_contract import GROUPS, LEGACY_USERS, deterministic_legacy_uuid
from backend.models import LegacyProfileRecovery, User

DESTINATION_ENV_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class RecoveryPreparationError(RuntimeError):
    """A source-to-destination recovery mapping was unsafe or incomplete."""


@dataclass(frozen=True)
class RecoveryCandidate:
    source_name: str
    user_id: uuid.UUID
    group_names: tuple[str, ...]


@dataclass(frozen=True)
class RecoveryPreparationResult:
    eligible_count: int
    would_create_count: int
    created_count: int
    pending_count: int
    claimed_count: int


def load_recovery_candidates(
    source_sqlite: Path,
    normalization_policy_path: Path | None = None,
) -> tuple[RecoveryCandidate, ...]:
    """Return only canonical users explicitly represented by the selected source."""
    policy = (
        importer._load_normalization_policy(normalization_policy_path)
        if normalization_policy_path is not None
        else None
    )
    inspection = importer.inspect_source(source_sqlite, policy)
    importer._raise_for_source_problems(inspection)

    source_names = sorted(
        {str(fact["user_name"]) for fact in inspection["logical_facts"]},
        key=str.casefold,
    )
    if not source_names:
        raise RecoveryPreparationError(
            "The selected legacy source contains no eligible canonical users"
        )
    if any(source_name not in LEGACY_USERS for source_name in source_names):
        raise RecoveryPreparationError(
            "The selected source produced an unknown canonical legacy user"
        )

    candidates = tuple(
        RecoveryCandidate(
            source_name=source_name,
            user_id=deterministic_legacy_uuid("user", source_name),
            group_names=tuple(
                group_name
                for group_name, members in GROUPS.items()
                if source_name in members
            ),
        )
        for source_name in source_names
    )
    candidate_ids = [candidate.user_id for candidate in candidates]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise RecoveryPreparationError(
            "The selected source produced an ambiguous deterministic user mapping"
        )
    return candidates


def prepare_recovery_entries(
    session: Session,
    candidates: Sequence[RecoveryCandidate],
    *,
    apply: bool,
) -> RecoveryPreparationResult:
    """Validate all mappings, then optionally insert missing pending rows atomically."""
    if not candidates:
        raise RecoveryPreparationError("At least one recovery candidate is required")
    candidate_ids = tuple(candidate.user_id for candidate in candidates)
    if len(candidate_ids) != len(set(candidate_ids)):
        raise RecoveryPreparationError("Recovery candidate mappings are ambiguous")

    try:
        user_statement = select_users = sa.select(User).where(
            User.id.in_(candidate_ids)
        )
        if apply:
            select_users = user_statement.with_for_update()
        destination_users = session.scalars(select_users).all()
        users_by_id = {user.id: user for user in destination_users}

        missing = [
            candidate.source_name
            for candidate in candidates
            if candidate.user_id not in users_by_id
        ]
        if missing:
            raise RecoveryPreparationError(
                "One or more source users are missing from the destination"
            )
        mismatched = [
            candidate.source_name
            for candidate in candidates
            if users_by_id[candidate.user_id].display_name != candidate.source_name
        ]
        if mismatched:
            raise RecoveryPreparationError(
                "A deterministic destination user does not match its source identity"
            )

        existing_rows = session.scalars(
            sa.select(LegacyProfileRecovery).where(
                LegacyProfileRecovery.user_id.in_(candidate_ids)
            )
        ).all()
        existing_ids = {row.user_id for row in existing_rows}
        missing_ids = [
            user_id for user_id in candidate_ids if user_id not in existing_ids
        ]
        if apply and missing_ids:
            session.execute(
                insert(LegacyProfileRecovery)
                .values([{"user_id": user_id} for user_id in missing_ids])
                .on_conflict_do_nothing(index_elements=["user_id"])
            )
            session.flush()

        final_rows = session.scalars(
            sa.select(LegacyProfileRecovery).where(
                LegacyProfileRecovery.user_id.in_(candidate_ids)
            )
        ).all()
        final_ids = {row.user_id for row in final_rows}
        created_count = len(final_ids - existing_ids) if apply else 0
        pending_count = sum(
            row.claimed_at is None and row.claimed_by_account_id is None
            for row in final_rows
        )
        claimed_count = len(final_rows) - pending_count
        if apply:
            session.commit()
        else:
            session.rollback()
        return RecoveryPreparationResult(
            eligible_count=len(candidates),
            would_create_count=len(missing_ids),
            created_count=created_count,
            pending_count=pending_count + (len(missing_ids) if not apply else 0),
            claimed_count=claimed_count,
        )
    except Exception:
        session.rollback()
        raise


def _destination_url(environment_name: str) -> str:
    if DESTINATION_ENV_PATTERN.fullmatch(environment_name) is None:
        raise RecoveryPreparationError(
            "Destination environment variable name is invalid"
        )
    value = os.getenv(environment_name)
    if value is None or not value.strip():
        raise RecoveryPreparationError(
            f"Destination environment variable {environment_name} is missing or blank"
        )
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m backend.cli.prepare_legacy_profile_recoveries",
        description=(
            "Prepare explicit pending recovery rows from one legacy SQLite source."
        ),
    )
    parser.add_argument("--source-sqlite", type=Path, required=True)
    parser.add_argument("--normalization-policy", type=Path)
    parser.add_argument("--destination-url-env", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    runtime = None
    try:
        arguments = build_parser().parse_args(argv)
        candidates = load_recovery_candidates(
            arguments.source_sqlite,
            arguments.normalization_policy,
        )
        runtime = create_database_runtime(
            _destination_url(arguments.destination_url_env)
        )
        validate_database_readiness(runtime)
        with runtime.open_session() as session:
            result = prepare_recovery_entries(
                session,
                candidates,
                apply=arguments.apply,
            )
        action = "apply" if arguments.apply else "dry-run"
        print(
            f"{action}: eligible={result.eligible_count} "
            f"would_create={result.would_create_count} "
            f"created={result.created_count} pending={result.pending_count} "
            f"claimed={result.claimed_count}"
        )
        return 0
    except (importer.ImporterError, RecoveryPreparationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(
            f"error: unexpected recovery preparation failure ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2
    finally:
        if runtime is not None:
            runtime.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
