import json

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from backend.cli.delete_account_data import main as deletion_main
from backend.db import repository_head_revision
from backend.models import Account
from backend.tests.test_account_data import (
    AccountDeletionCases,
    seed_personal_data,
    snapshot,
)


@pytest.fixture
def lifecycle_engine(postgres_engine, db_session):
    # Reuse the real migrated disposable PostgreSQL database and cleanup fixture.
    yield postgres_engine


class TestPostgresAccountDeletion(AccountDeletionCases):
    pass


def test_cli_uses_real_readiness_and_safe_default(
    lifecycle_engine, postgres_database_url, monkeypatch, capsys
):
    ids = seed_personal_data(lifecycle_engine)
    monkeypatch.setenv("DATABASE_URL", postgres_database_url)
    with lifecycle_engine.connect() as connection:
        revision = connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
    assert revision == repository_head_revision() == "0012_session_event_email_outbox"
    before = snapshot(lifecycle_engine)
    assert deletion_main(["--account-id", str(ids["account"])]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert snapshot(lifecycle_engine) == before
    assert deletion_main(["--account-id", str(ids["account"]), "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is True
    with Session(lifecycle_engine) as session:
        assert session.get(Account, ids["account"]) is None
