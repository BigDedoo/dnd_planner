from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.auth import get_or_create_account
from backend.models import Account, AccountIdentity


def _assert_integrity_error(session: Session, value: object) -> None:
    with pytest.raises(IntegrityError):
        with session.begin():
            session.add(value)
            session.flush()


def test_schema_catalog_contains_phase_2a_objects(postgres_engine: Engine) -> None:
    inspector = sa.inspect(postgres_engine)
    assert {"accounts", "account_identities"}.issubset(inspector.get_table_names())

    expected_primary_keys = {
        "accounts": ("pk_accounts", ["id"]),
        "account_identities": ("pk_account_identities", ["id"]),
    }
    for table_name, (constraint_name, columns) in expected_primary_keys.items():
        primary_key = inspector.get_pk_constraint(table_name)
        assert primary_key["name"] == constraint_name
        assert primary_key["constrained_columns"] == columns

    for table_name, uuid_columns in {
        "accounts": {"id"},
        "account_identities": {"id", "account_id"},
    }.items():
        columns = {
            column["name"]: column for column in inspector.get_columns(table_name)
        }
        for column_name in uuid_columns:
            assert isinstance(columns[column_name]["type"], postgresql.UUID)

    expected_checks = {
        "accounts": {
            "ck_accounts_email_not_blank",
            "ck_accounts_display_name_not_blank",
        },
        "account_identities": {
            "ck_account_identities_provider_not_blank",
            "ck_account_identities_provider_subject_not_blank",
        },
    }
    for table_name, expected_names in expected_checks.items():
        actual_names = {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
        }
        assert expected_names.issubset(actual_names)


def test_accounts_table_constraints(db_session: Session) -> None:
    # Blank email rejected
    _assert_integrity_error(db_session, Account(email="   "))
    # Blank display_name rejected
    _assert_integrity_error(db_session, Account(display_name="   "))

    # Valid account with nullable fields
    with db_session.begin():
        valid_account = Account(email="test@example.com", display_name="Test User")
        db_session.add(valid_account)
    assert valid_account.id is not None


def test_account_identities_table_constraints_and_cascade(
    db_session: Session,
) -> None:
    with db_session.begin():
        account = Account(email="owner@example.com", display_name="Owner")
        db_session.add(account)
        db_session.flush()

        identity = AccountIdentity(
            account_id=account.id,
            provider="clerk",
            provider_subject="clerk_subject_123",
        )
        db_session.add(identity)

    # Unique constraint on (provider, provider_subject)
    with pytest.raises(IntegrityError):
        with db_session.begin():
            duplicate_identity = AccountIdentity(
                account_id=account.id,
                provider="clerk",
                provider_subject="clerk_subject_123",
            )
            db_session.add(duplicate_identity)
            db_session.flush()

    # Cascade delete on account
    with db_session.begin():
        db_session.delete(account)

    remaining_identities = db_session.scalars(
        sa.select(AccountIdentity).where(
            AccountIdentity.provider_subject == "clerk_subject_123"
        )
    ).all()
    assert len(remaining_identities) == 0


def test_postgres_get_or_create_account_idempotence_and_concurrency(
    db_session: Session,
) -> None:
    acc1 = get_or_create_account(
        session=db_session,
        provider="clerk",
        provider_subject="user_pg_test_1",
        email="pg1@example.com",
        display_name="PG User 1",
    )
    db_session.commit()

    acc2 = get_or_create_account(
        session=db_session,
        provider="clerk",
        provider_subject="user_pg_test_1",
        email="pg1@example.com",
        display_name="PG User 1",
    )

    assert acc1.id == acc2.id
    assert acc1.email == "pg1@example.com"
