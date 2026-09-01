from __future__ import annotations

import hashlib
import uuid
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.cli import reconcile_legacy_availability as reconciliation
from backend.legacy_contract import deterministic_legacy_uuid
from backend.models import Availability, AvailabilityStatus, User
from backend.tests.test_import_legacy_sqlite import (
    create_synthetic_source,
    write_normalization_policy,
)


def _expected(
    user_name: str,
    day: date,
    status: AvailabilityStatus,
) -> reconciliation.ExpectedAvailability:
    return reconciliation.ExpectedAvailability(
        user_id=deterministic_legacy_uuid("user", user_name),
        user_name=user_name,
        day=day,
        status=status,
    )


def test_reconciliation_inserts_updates_preserves_and_is_idempotent(
    db_session: Session,
) -> None:
    expected_rows = (
        _expected("Quentin", date(2026, 8, 1), AvailabilityStatus.AVAILABLE),
        _expected("Arnaud", date(2026, 8, 2), AvailabilityStatus.MAYBE),
        _expected("Dembe", date(2026, 8, 3), AvailabilityStatus.UNAVAILABLE),
    )
    users = [User(id=row.user_id, display_name=row.user_name) for row in expected_rows]
    unrelated_user = User(id=uuid.uuid4(), display_name="Unrelated")
    unrelated_row = Availability(
        user_id=unrelated_user.id,
        day=date(2026, 8, 4),
        status=AvailabilityStatus.AVAILABLE,
    )
    db_session.add_all(
        [
            *users,
            unrelated_user,
            Availability(
                user_id=expected_rows[1].user_id,
                day=expected_rows[1].day,
                status=AvailabilityStatus.UNAVAILABLE,
            ),
            Availability(
                user_id=expected_rows[2].user_id,
                day=expected_rows[2].day,
                status=AvailabilityStatus.UNAVAILABLE,
            ),
            unrelated_row,
        ]
    )
    db_session.commit()

    dry_run = reconciliation.reconcile_availability(
        db_session,
        expected_rows,
        apply=False,
    )
    assert dry_run == reconciliation.AvailabilityReconciliationResult(
        insert_count=1,
        update_count=1,
        unchanged_count=1,
        delete_count=0,
        verified_count=3,
    )
    assert (
        db_session.get(
            Availability,
            (expected_rows[1].user_id, expected_rows[1].day),
        ).status
        == AvailabilityStatus.UNAVAILABLE
    )

    with pytest.raises(
        reconciliation.AvailabilityReconciliationError,
        match="differ from approved counts",
    ):
        reconciliation.reconcile_availability(
            db_session,
            expected_rows,
            apply=True,
            required_counts=reconciliation.RequiredReconciliationCounts(0, 0, 3),
        )
    assert (
        db_session.get(
            Availability,
            (expected_rows[1].user_id, expected_rows[1].day),
        ).status
        == AvailabilityStatus.UNAVAILABLE
    )

    applied = reconciliation.reconcile_availability(
        db_session,
        expected_rows,
        apply=True,
        required_counts=reconciliation.RequiredReconciliationCounts(1, 1, 1),
    )
    assert applied.insert_count == 1
    assert applied.update_count == 1
    assert applied.delete_count == 0
    db_session.expire_all()
    for expected in expected_rows:
        assert (
            db_session.get(Availability, (expected.user_id, expected.day)).status
            == expected.status
        )
    assert (
        db_session.get(
            Availability,
            (unrelated_user.id, unrelated_row.day),
        ).status
        == AvailabilityStatus.AVAILABLE
    )
    assert db_session.scalar(sa.select(sa.func.count()).select_from(Availability)) == 4

    rerun = reconciliation.reconcile_availability(
        db_session,
        expected_rows,
        apply=False,
    )
    assert rerun == reconciliation.AvailabilityReconciliationResult(
        insert_count=0,
        update_count=0,
        unchanged_count=3,
        delete_count=0,
        verified_count=3,
    )


def test_reconciliation_rejects_unexpected_legacy_user_availability(
    db_session: Session,
) -> None:
    expected = _expected(
        "Quentin",
        date(2026, 8, 1),
        AvailabilityStatus.AVAILABLE,
    )
    db_session.add_all(
        [
            User(id=expected.user_id, display_name=expected.user_name),
            Availability(
                user_id=expected.user_id,
                day=date(2026, 8, 2),
                status=AvailabilityStatus.MAYBE,
            ),
        ]
    )
    db_session.commit()

    with pytest.raises(
        reconciliation.AvailabilityReconciliationError,
        match="production-only availability",
    ):
        reconciliation.reconcile_availability(
            db_session,
            (expected,),
            apply=True,
            required_counts=reconciliation.RequiredReconciliationCounts(1, 0, 0),
        )

    assert db_session.scalar(sa.select(sa.func.count()).select_from(Availability)) == 1


def test_source_hash_and_approved_counts_fail_closed(tmp_path: Path) -> None:
    source = create_synthetic_source(
        tmp_path / "source.sqlite",
        [("Green flag", "Quentin", "2026-08-01", "Available")],
    )

    with pytest.raises(
        reconciliation.AvailabilityReconciliationError,
        match="SHA-256",
    ):
        reconciliation.load_expected_availability(
            source,
            None,
            "0" * 64,
        )

    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    policy = write_normalization_policy(tmp_path / "normalization-policy.json")
    with pytest.raises(
        reconciliation.AvailabilityReconciliationError,
        match="approved legacy counts",
    ):
        reconciliation.load_expected_availability(
            source,
            policy,
            source_hash,
        )
