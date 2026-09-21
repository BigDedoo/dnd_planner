from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Engine


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
