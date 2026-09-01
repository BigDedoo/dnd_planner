from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.legacy_profile_recovery import (
    RecoveryProfileClaimedError,
    claim_legacy_profile,
)
from backend.models import Account, LegacyProfileRecovery, User


def test_legacy_profile_recovery_schema_is_explicit_and_auditable(
    postgres_engine: Engine,
) -> None:
    inspector = sa.inspect(postgres_engine)
    primary_key = inspector.get_pk_constraint("legacy_profile_recoveries")
    assert primary_key["name"] == "pk_legacy_profile_recoveries"
    assert primary_key["constrained_columns"] == ["user_id"]
    assert {
        constraint["name"]
        for constraint in inspector.get_check_constraints("legacy_profile_recoveries")
    } == {"ck_legacy_profile_recoveries_claim_state"}
    assert {
        index["name"] for index in inspector.get_indexes("legacy_profile_recoveries")
    } == {
        "ix_legacy_profile_recoveries_claimed_at",
        "ix_legacy_profile_recoveries_claimed_by_account_id",
    }
    foreign_keys = {
        key["name"]: key
        for key in inspector.get_foreign_keys("legacy_profile_recoveries")
    }
    assert foreign_keys["fk_legacy_profile_recoveries_user_id_users"]["options"] == {
        "ondelete": "CASCADE"
    }
    assert foreign_keys["fk_legacy_profile_recoveries_claimed_by_account_id_accounts"][
        "options"
    ] == {"ondelete": "RESTRICT"}


def test_concurrent_claim_allows_exactly_one_account(postgres_engine: Engine) -> None:
    with Session(postgres_engine, expire_on_commit=False) as session:
        first_account = Account(display_name="First claimant")
        second_account = Account(display_name="Second claimant")
        old_account = Account(display_name="Old development account")
        user = User(account=old_account, display_name="Concurrent legacy hero")
        session.add_all([first_account, second_account, old_account, user])
        session.flush()
        session.add(LegacyProfileRecovery(user_id=user.id))
        session.commit()
        account_ids = (first_account.id, second_account.id)
        user_id = user.id
        old_account_id = old_account.id

    barrier = Barrier(2)

    def attempt(account_id):
        with Session(postgres_engine, expire_on_commit=False) as session:
            barrier.wait(timeout=5)
            try:
                claimed = claim_legacy_profile(session, account_id, user_id)
                return "claimed", claimed.account_id
            except RecoveryProfileClaimedError:
                return "conflict", account_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(attempt, account_ids))

    assert sorted(outcome[0] for outcome in outcomes) == ["claimed", "conflict"]
    winner = next(account_id for status, account_id in outcomes if status == "claimed")
    with Session(postgres_engine) as session:
        user = session.get(User, user_id)
        recovery = session.get(LegacyProfileRecovery, user_id)
        assert user is not None and user.account_id == winner
        assert recovery is not None and recovery.claimed_by_account_id == winner
        assert recovery.claimed_at is not None
        assert session.get(Account, old_account_id) is not None
