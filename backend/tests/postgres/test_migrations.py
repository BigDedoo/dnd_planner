from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.models import Account, AccountIdentity, User

DOMAIN_TABLES = {
    "users",
    "groups",
    "group_memberships",
    "availability",
    "group_availability",
    "confirmed_sessions",
    "confirmed_session_rsvps",
    "session_notification_deliveries",
    "session_event_email_outbox",
    "group_invites",
    "legacy_profile_recoveries",
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
    assert head_revision == "0013_group_availability_override"
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


def test_reminder_preference_migration_defaults_constraint_and_downgrade(
    postgres_engine,
    alembic_config,
    run_alembic,
    db_session,
):
    user_id = uuid.uuid4()
    try:
        run_alembic(alembic_config, "downgrade", "0010_legacy_profile_recoveries")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO users (id, display_name, timezone) VALUES (:id, 'Existing player', 'UTC')"
                ),
                {"id": user_id},
            )
        run_alembic(alembic_config, "upgrade", "head")
        with Session(postgres_engine) as session:
            assert session.get(User, user_id).session_reminder_minutes == 1440
            new_user = User(display_name="New player")
            off_user = User(display_name="Opted out", session_reminder_minutes=None)
            session.add_all([new_user, off_user])
            session.commit()
            assert new_user.session_reminder_minutes == 1440
            assert off_user.session_reminder_minutes is None
        for invalid in [-1, 0, 59, 181, 10081]:
            with (
                pytest.raises(sa.exc.IntegrityError),
                postgres_engine.begin() as connection,
            ):
                connection.execute(
                    sa.text(
                        "UPDATE users SET session_reminder_minutes=:value WHERE id=:id"
                    ),
                    {"value": invalid, "id": user_id},
                )
        for valid in [None, 60, 180, 720, 1440, 4320, 10080]:
            with postgres_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "UPDATE users SET session_reminder_minutes=:value WHERE id=:id"
                    ),
                    {"value": valid, "id": user_id},
                )
        run_alembic(alembic_config, "downgrade", "0010_legacy_profile_recoveries")
        assert "session_reminder_minutes" not in {
            col["name"] for col in sa.inspect(postgres_engine).get_columns("users")
        }
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text("SELECT display_name FROM users WHERE id=:id"),
                    {"id": user_id},
                )
                == "Existing player"
            )
    finally:
        run_alembic(alembic_config, "upgrade", "head")


def test_event_email_migration_is_empty_and_preserves_historical_deliveries(
    postgres_engine, alembic_config, run_alembic, db_session
):
    user_id, group_id, session_id, delivery_id = (uuid.uuid4() for _ in range(4))
    try:
        run_alembic(alembic_config, "downgrade", "0011_session_reminder_minutes")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO users (id, display_name, timezone) VALUES (:id, 'Existing player', 'UTC')"
                ),
                {"id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO groups (id, name, timezone) VALUES (:id, 'Old group', 'UTC')"
                ),
                {"id": group_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO confirmed_sessions (id, group_id, day, confirmed_by_user_id) "
                    "VALUES (:id, :group_id, '2026-10-06', :user_id)"
                ),
                {"id": session_id, "group_id": group_id, "user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO session_notification_deliveries "
                    "(id, session_id, recipient_user_id, kind, dedupe_key) "
                    "VALUES (:id, :session_id, :user_id, 'session_scheduled', 'old-log-only')"
                ),
                {"id": delivery_id, "session_id": session_id, "user_id": user_id},
            )
        run_alembic(alembic_config, "upgrade", "head")
        inspector = sa.inspect(postgres_engine)
        preference = next(
            col
            for col in inspector.get_columns("users")
            if col["name"] == "important_session_emails_enabled"
        )
        assert preference["nullable"] is False
        assert "session_event_email_outbox" in inspector.get_table_names()
        assert {
            check["name"]
            for check in inspector.get_check_constraints("session_event_email_outbox")
        } == {
            "ck_session_event_email_outbox_kind",
            "ck_session_event_email_outbox_attempt_count",
        }
        assert {
            index["name"]
            for index in inspector.get_indexes("session_event_email_outbox")
        } == {
            "ix_session_event_email_outbox_due",
            "uq_session_event_email_outbox_dedupe_key",
        }
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT important_session_emails_enabled FROM users WHERE id=:id"
                    ),
                    {"id": user_id},
                )
                is True
            )
            assert (
                connection.scalar(
                    sa.text("SELECT count(*) FROM session_event_email_outbox")
                )
                == 0
            )
            assert (
                connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM session_notification_deliveries WHERE id=:id"
                    ),
                    {"id": delivery_id},
                )
                == 1
            )
        with (
            pytest.raises(sa.exc.IntegrityError),
            postgres_engine.begin() as connection,
        ):
            connection.execute(
                sa.text(
                    "UPDATE users SET important_session_emails_enabled=NULL WHERE id=:id"
                ),
                {"id": user_id},
            )
        run_alembic(alembic_config, "downgrade", "0011_session_reminder_minutes")
        assert (
            "session_event_email_outbox"
            not in sa.inspect(postgres_engine).get_table_names()
        )
        assert "important_session_emails_enabled" not in {
            col["name"] for col in sa.inspect(postgres_engine).get_columns("users")
        }
    finally:
        run_alembic(alembic_config, "upgrade", "head")


def test_group_availability_migration_preserves_existing_data_and_downgrades(
    postgres_engine, alembic_config, run_alembic, db_session
):
    user_id, group_id, event_id = (uuid.uuid4() for _ in range(3))
    day = date(2026, 10, 12)
    try:
        run_alembic(alembic_config, "downgrade", "0012_session_event_email_outbox")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO users (id, display_name, timezone) VALUES (:id, 'Existing', 'UTC')"
                ),
                {"id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO groups (id, name, timezone) VALUES (:id, 'Existing group', 'UTC')"
                ),
                {"id": group_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO group_memberships (group_id, user_id, role, display_order) VALUES (:group_id, :user_id, 'owner', 0)"
                ),
                {"group_id": group_id, "user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO availability (user_id, day, status) VALUES (:user_id, :day, 'available')"
                ),
                {"user_id": user_id, "day": day},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO confirmed_sessions (id, group_id, day, confirmed_by_user_id) VALUES (:id, :group_id, :day, :user_id)"
                ),
                {"id": event_id, "group_id": group_id, "day": day, "user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO confirmed_session_rsvps (session_id, user_id, status) VALUES (:session_id, :user_id, 'going')"
                ),
                {"session_id": event_id, "user_id": user_id},
            )
        with postgres_engine.connect() as connection:
            before = connection.execute(
                sa.text(
                    "SELECT user_id, day, status, updated_at FROM availability WHERE user_id=:id"
                ),
                {"id": user_id},
            ).one()
        run_alembic(alembic_config, "upgrade", "head")
        inspector = sa.inspect(postgres_engine)
        assert "group_availability" in inspector.get_table_names()
        assert {
            column["name"] for column in inspector.get_columns("group_memberships")
        } >= {"availability_mode", "separate_availability_initialized"}
        with postgres_engine.connect() as connection:
            assert connection.execute(
                sa.text(
                    "SELECT availability_mode, separate_availability_initialized FROM group_memberships WHERE group_id=:id"
                ),
                {"id": group_id},
            ).one() == ("global", False)
            assert (
                connection.scalar(sa.text("SELECT count(*) FROM group_availability"))
                == 0
            )
            assert (
                connection.execute(
                    sa.text(
                        "SELECT user_id, day, status, updated_at FROM availability WHERE user_id=:id"
                    ),
                    {"id": user_id},
                ).one()
                == before
            )
            for table in (
                "users",
                "groups",
                "group_memberships",
                "confirmed_sessions",
                "confirmed_session_rsvps",
            ):
                assert connection.scalar(sa.text(f"SELECT count(*) FROM {table}")) == 1
        run_alembic(alembic_config, "downgrade", "0012_session_event_email_outbox")
        inspector = sa.inspect(postgres_engine)
        assert "group_availability" not in inspector.get_table_names()
        assert "availability_mode" not in {
            column["name"] for column in inspector.get_columns("group_memberships")
        }
        with postgres_engine.connect() as connection:
            assert (
                connection.execute(
                    sa.text(
                        "SELECT user_id, day, status, updated_at FROM availability WHERE user_id=:id"
                    ),
                    {"id": user_id},
                ).one()
                == before
            )
    finally:
        run_alembic(alembic_config, "upgrade", "head")


def test_imports_create_no_postgresql_schema(
    postgres_engine: Engine,
    postgres_database_url: str,
    alembic_config: Config,
    run_alembic: Callable[[Config, str, str], None],
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

        assert DOMAIN_TABLES.isdisjoint(sa.inspect(postgres_engine).get_table_names())
    finally:
        run_alembic(alembic_config, "upgrade", "head")

        assert _current_revision(postgres_engine) == "0013_group_availability_override"


def test_scheduled_session_migration_preserves_date_only_sessions(
    postgres_engine: Engine,
    alembic_config: Config,
    run_alembic: Callable[[Config, str, str], None],
) -> None:
    user_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session_id = uuid.uuid4()
    try:
        run_alembic(alembic_config, "downgrade", "0007_onboarding_group_nicknames")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO users (id, display_name, timezone) "
                    "VALUES (:id, 'Legacy player', 'UTC')"
                ),
                {"id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO groups (id, name, timezone) "
                    "VALUES (:id, 'Legacy group', 'UTC')"
                ),
                {"id": group_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO group_memberships (group_id, user_id, role, display_order) "
                    "VALUES (:group_id, :user_id, 'owner', 0)"
                ),
                {"group_id": group_id, "user_id": user_id},
            )
            connection.execute(
                sa.text(
                    "INSERT INTO confirmed_sessions (id, group_id, day, confirmed_by_user_id) "
                    "VALUES (:id, :group_id, '2026-08-22', :user_id)"
                ),
                {"id": session_id, "group_id": group_id, "user_id": user_id},
            )

        run_alembic(alembic_config, "upgrade", "head")
        with postgres_engine.connect() as connection:
            row = connection.execute(
                sa.text(
                    "SELECT title, start_time, duration_minutes, notes, "
                    "updated_at, cancelled_at, cancelled_by_user_id "
                    "FROM confirmed_sessions WHERE id = :id"
                ),
                {"id": session_id},
            ).one()
            assert row[:4] == (None, None, None, None)
            assert row.updated_at is not None
            assert row.cancelled_at is None
            assert row.cancelled_by_user_id is None
            assert (
                connection.scalar(
                    sa.text("SELECT count(*) FROM confirmed_session_rsvps")
                )
                == 0
            )
    finally:
        run_alembic(alembic_config, "upgrade", "head")
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "TRUNCATE TABLE confirmed_session_rsvps, confirmed_sessions, "
                    "availability, group_memberships, groups, users, "
                    "account_identities, accounts CASCADE"
                )
            )


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

        assert _current_revision(postgres_engine) == "0013_group_availability_override"
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
                    "TRUNCATE TABLE group_invites, confirmed_session_rsvps, confirmed_sessions, availability, group_memberships, groups, users, "
                    "account_identities, accounts CASCADE"
                )
            )
