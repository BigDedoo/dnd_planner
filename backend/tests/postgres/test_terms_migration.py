"""An additive migration must never accept legal terms for existing accounts."""

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session

from backend.models import Account
from backend.terms import CURRENT_TERMS_VERSION


def test_terms_upgrade_preserves_accounts_null_defaults_and_utc(
    postgres_engine, alembic_config, run_alembic
):
    account_id = uuid.uuid4()
    try:
        run_alembic(alembic_config, "downgrade", "0013_group_availability_override")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO accounts (id, display_name) VALUES (:id, 'Existing account')"
                ),
                {"id": account_id},
            )
        run_alembic(alembic_config, "upgrade", "head")
        command.check(alembic_config)
        columns = {
            column["name"]: column
            for column in sa.inspect(postgres_engine).get_columns("accounts")
        }
        assert columns["terms_version"]["nullable"]
        assert columns["terms_accepted_at"]["nullable"]
        assert columns["terms_accepted_at"]["type"].timezone
        with Session(postgres_engine) as session:
            account = session.get(Account, account_id)
            assert account.display_name == "Existing account"
            assert account.terms_version is None and account.terms_accepted_at is None
            account.terms_version = CURRENT_TERMS_VERSION
            with pytest.raises(sa.exc.IntegrityError):
                session.commit()
            session.rollback()
            account.terms_version = CURRENT_TERMS_VERSION
            expected_instant = datetime.now(timezone.utc)
            account.terms_accepted_at = expected_instant
            session.commit()
            session.refresh(account)
            # PostgreSQL returns timestamptz in the connection's timezone.
            # Assert awareness and the same instant, not a forced display offset.
            assert account.terms_accepted_at.tzinfo is not None
            assert (
                account.terms_accepted_at.astimezone(timezone.utc) == expected_instant
            )
            accepted_at = account.terms_accepted_at
            account.display_name = "Changed profile"
            session.commit()
            session.refresh(account)
            assert account.terms_accepted_at == accepted_at
        run_alembic(alembic_config, "downgrade", "0013_group_availability_override")
        assert "terms_version" not in {
            c["name"] for c in sa.inspect(postgres_engine).get_columns("accounts")
        }
    finally:
        run_alembic(alembic_config, "upgrade", "head")
