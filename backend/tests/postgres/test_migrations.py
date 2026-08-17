from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models import Account, AccountIdentity, User

DOMAIN_TABLES = {
    "users",
    "groups",
    "group_memberships",
    "availability",
    "confirmed_sessions",
    "group_invites",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_migration_upgrade_check_downgrade_and_reupgrade(
    postgres_engine: Engine,
    alembic_config: Config,
    run_alembic: Callable[[Config, str, str], None],
) -> None:
    head_revision = ScriptDirectory.from_config(alembic_config).get_current_head()
    assert head_revision == "0007_onboarding_group_nicknames"
    assert _current_revision(postgres_engine) == head_revision
    assert DOMAIN_TABLES.issubset(sa.inspect(postgres_engine).get_table_names())

    command.check(alembic_config)

    try:
        run_alembic(alembic_config, "downgrade", "base")
        inspector = sa.inspect(postgres_engine)
        assert DOMAIN_TABLES.isdisjoint(inspector.get_table_names())
        assert _current_revision(postgres_engine) is None

        if "alembic_version" in inspector.get_table_names():
            with postgres_engine.connect() as connection:
                assert (
                    connection.scalar(sa.text("SELECT count(*) FROM alembic_version"))
                    == 0
                )
    finally:
        run_alembic(alembic_config, "upgrade", "head")

    assert _current_revision(postgres_engine) == head_revision
    with Session(postgres_engine) as session, session.begin():
        session.add(User(display_name="Migration smoke test"))
    with Session(postgres_engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(User)) == 1


def test_imports_and_legacy_app_startup_create_no_postgresql_schema(
    postgres_engine: Engine,
    postgres_database_url: str,
    alembic_config: Config,
    run_alembic: Callable[[Config, str, str], None],
    tmp_path: Path,
    legacy_app_factory: Callable[[Settings], FastAPI],
) -> None:
    try:
        run_alembic(alembic_config, "downgrade", "base")
        assert DOMAIN_TABLES.isdisjoint(sa.inspect(postgres_engine).get_table_names())

        environment = os.environ.copy()
        environment["DATABASE_URL"] = postgres_database_url
        import_result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import backend.db; import backend.models",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert import_result.returncode == 0, import_result.stderr
        assert DOMAIN_TABLES.isdisjoint(sa.inspect(postgres_engine).get_table_names())

        legacy_path = tmp_path / "phase1a-legacy-startup.db"
        legacy_settings = Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="CRITICAL",
            DATABASE_PATH=legacy_path,
            DATABASE_URL=None,
            CORS_ALLOWED_ORIGINS=["http://testserver"],
        )
        with TestClient(legacy_app_factory(legacy_settings)) as client:
            assert client.get("/test-health").json() == {"status": "ok"}
        assert legacy_path.is_file()
        assert legacy_settings.database_url is None
        assert DOMAIN_TABLES.isdisjoint(sa.inspect(postgres_engine).get_table_names())
    finally:
        run_alembic(alembic_config, "upgrade", "head")

        assert _current_revision(postgres_engine) == "0007_onboarding_group_nicknames"


def test_clerk_profile_migration_preserves_phase_2b_identity_and_domain_data(
    postgres_engine: Engine,
    alembic_config: Config,
    run_alembic: Callable[[Config, str, str], None],
) -> None:
    account_id = uuid.uuid4()
    identity_id = uuid.uuid4()
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    try:
        run_alembic(
            alembic_config,
            "downgrade",
            "0003_phase_2b_user_accounts",
        )
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO accounts (id, email, display_name) "
                    "VALUES (:id, :email, :display_name)"
                ),
                {
                    "id": account_id,
                    "email": "migration@example.com",
                    "display_name": "Migration Account",
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO account_identities "
                    "(id, account_id, provider, provider_subject) "
                    "VALUES (:id, :account_id, 'clerk', 'migration_subject')"
                ),
                {"id": identity_id, "account_id": account_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO users (id, account_id, display_name, timezone) "
                    "VALUES (:id, :account_id, 'Migration User', 'UTC')"
                ),
                {"id": user_id, "account_id": account_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO groups (id, name, timezone) "
                    "VALUES (:id, 'Migration Group', 'UTC')"
                ),
                {"id": group_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO group_memberships "
                    "(group_id, user_id, role, display_order) "
                    "VALUES (:group_id, :user_id, 'owner', 0)"
                ),
                {"group_id": group_id, "user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO availability (user_id, day, status) "
                    "VALUES (:user_id, :day, 'available')"
                ),
                {"user_id": user_id, "day": date(2026, 8, 16)},
            )

        run_alembic(alembic_config, "upgrade", "head")

        assert _current_revision(postgres_engine) == "0007_onboarding_group_nicknames"
        account_columns = {
            column["name"]: column
            for column in sa.inspect(postgres_engine).get_columns("accounts")
        }
        assert account_columns["username"]["nullable"] is True
        assert account_columns["username"]["type"].length == 120
        assert account_columns["profile_synced_at"]["nullable"] is True
        membership_columns = {
            column["name"]: column
            for column in sa.inspect(postgres_engine).get_columns("group_memberships")
        }
        assert membership_columns["nickname"]["nullable"] is True
        assert membership_columns["nickname"]["type"].length == 120

        with Session(postgres_engine) as session:
            account = session.get(Account, account_id)
            identity = session.get(AccountIdentity, identity_id)
            assert account is not None
            assert account.email == "migration@example.com"
            assert account.username is None
            assert account.profile_synced_at is None
            assert identity is not None
            assert identity.account_id == account_id
            assert session.scalar(sa.text("SELECT count(*) FROM users")) == 1
            assert session.scalar(sa.text("SELECT count(*) FROM groups")) == 1
            assert (
                session.scalar(sa.text("SELECT count(*) FROM group_memberships")) == 1
            )
            assert (
                session.scalar(sa.text("SELECT nickname FROM group_memberships"))
                is None
            )
            assert session.scalar(sa.text("SELECT count(*) FROM availability")) == 1
    finally:
        run_alembic(alembic_config, "upgrade", "head")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "TRUNCATE TABLE group_invites, confirmed_sessions, availability, group_memberships, groups, users, "
                    "account_identities, accounts CASCADE"
                )
            )
