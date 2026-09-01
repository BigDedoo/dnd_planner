from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.cli import prepare_legacy_profile_recoveries as preparation
from backend.models import Account, LegacyProfileRecovery, User
from backend.tests.test_import_legacy_sqlite import create_synthetic_source


def _source(path: Path) -> Path:
    return create_synthetic_source(
        path,
        [
            ("Green flag", "Quentin", "2026-01-01", "Available"),
            ("Underdark", "Quentin", "2026-01-01", "Available"),
            ("1D6", "Dembe", "2026-02-02", "Maybe"),
        ],
    )


def test_dry_run_apply_and_rerun_are_explicit_and_idempotent(
    db_session: Session,
    tmp_path: Path,
) -> None:
    candidates = preparation.load_recovery_candidates(_source(tmp_path / "source.db"))
    linked_account = Account(display_name="Old development identity")
    linked_user = User(
        id=candidates[0].user_id,
        account=linked_account,
        display_name=candidates[0].source_name,
    )
    second_user = User(
        id=candidates[1].user_id,
        display_name=candidates[1].source_name,
    )
    unrelated_legacy_user = User(
        id=uuid.uuid4(),
        display_name="Unrelated local user",
    )
    db_session.add_all(
        [linked_account, linked_user, second_user, unrelated_legacy_user]
    )
    db_session.commit()
    linked_account_id = linked_account.id

    dry_run = preparation.prepare_recovery_entries(
        db_session,
        candidates,
        apply=False,
    )
    assert dry_run.eligible_count == 2
    assert dry_run.would_create_count == 2
    assert dry_run.created_count == 0
    assert (
        db_session.scalar(sa.select(sa.func.count()).select_from(LegacyProfileRecovery))
        == 0
    )

    applied = preparation.prepare_recovery_entries(
        db_session,
        candidates,
        apply=True,
    )
    assert applied.created_count == 2
    assert applied.pending_count == 2
    assert applied.claimed_count == 0
    assert db_session.scalars(sa.select(LegacyProfileRecovery)).all()

    rerun = preparation.prepare_recovery_entries(
        db_session,
        candidates,
        apply=True,
    )
    assert rerun.created_count == 0
    assert rerun.pending_count == 2
    assert db_session.get(User, linked_user.id).account_id == linked_account_id
    assert db_session.get(LegacyProfileRecovery, unrelated_legacy_user.id) is None


def test_missing_destination_user_fails_without_partial_rows(
    db_session: Session,
    tmp_path: Path,
) -> None:
    candidates = preparation.load_recovery_candidates(_source(tmp_path / "source.db"))
    db_session.add(
        User(
            id=candidates[0].user_id,
            display_name=candidates[0].source_name,
        )
    )
    db_session.commit()

    with pytest.raises(
        preparation.RecoveryPreparationError,
        match="missing from the destination",
    ):
        preparation.prepare_recovery_entries(db_session, candidates, apply=True)

    assert (
        db_session.scalar(sa.select(sa.func.count()).select_from(LegacyProfileRecovery))
        == 0
    )


def test_ambiguous_deterministic_mapping_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_id = uuid.uuid4()
    monkeypatch.setattr(
        preparation,
        "deterministic_legacy_uuid",
        lambda kind, value: shared_id,
    )

    with pytest.raises(
        preparation.RecoveryPreparationError,
        match="ambiguous deterministic user mapping",
    ):
        preparation.load_recovery_candidates(_source(tmp_path / "source.db"))
