from __future__ import annotations

import os
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import URL
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.db import create_database_runtime, validate_database_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE_PREFIX = "dnd_planner_test_"
APPROVED_ADMIN_HOSTS = {"localhost", "127.0.0.1", "::1", "postgres"}
DOMAIN_TABLES = {
    "users",
    "groups",
    "group_memberships",
    "availability",
    "confirmed_sessions",
    "confirmed_session_rsvps",
    "group_invites",
}
_unexpected_postgres_skips: list[str] = []


def _validate_admin_url(raw_url: str) -> URL:
    database_url = validate_database_url(raw_url)
    if database_url.host not in APPROVED_ADMIN_HOSTS:
        raise pytest.UsageError(
            "TEST_DATABASE_ADMIN_URL host is not an approved local/CI host"
        )
    if database_url.database != "postgres":
        raise pytest.UsageError(
            "TEST_DATABASE_ADMIN_URL must target the postgres maintenance database"
        )
    return database_url


def _validate_generated_database_name(database_name: str) -> None:
    if (
        not database_name.startswith(TEST_DATABASE_PREFIX)
        or re.fullmatch(r"dnd_planner_test_[a-f0-9]{16}", database_name) is None
    ):
        raise RuntimeError("Refusing unsafe disposable database name")


def _quoted_database_name(database_name: str) -> str:
    _validate_generated_database_name(database_name)
    return f'"{database_name}"'


def _alembic_config(database_url: str) -> Config:
    migration_config = Config(str(REPOSITORY_ROOT / "alembic.ini"))
    migration_config.attributes["database_url"] = database_url
    return migration_config


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    normalized_node_id = report.nodeid.replace("\\", "/")
    if (
        report.skipped
        and "/postgres/" in f"/{normalized_node_id}"
        and not getattr(report, "wasxfail", False)
    ):
        _unexpected_postgres_skips.append(report.nodeid)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if os.getenv("REQUIRE_POSTGRES_TESTS") == "1" and _unexpected_postgres_skips:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(scope="session")
def postgres_admin_url() -> URL:
    raw_url = os.getenv("TEST_DATABASE_ADMIN_URL")
    if not raw_url:
        pytest.skip(
            "PostgreSQL Phase 1A/1B/1C tests skipped: "
            "TEST_DATABASE_ADMIN_URL is not set"
        )
    return _validate_admin_url(raw_url)


@pytest.fixture(scope="session", autouse=True)
def require_postgres_admin_url(postgres_admin_url: URL) -> None:
    del postgres_admin_url


@contextmanager
def _temporary_postgres_database(postgres_admin_url: URL) -> Iterator[str]:
    database_name = f"{TEST_DATABASE_PREFIX}{secrets.token_hex(8)}"
    quoted_database_name = _quoted_database_name(database_name)
    admin_engine = sa.create_engine(
        postgres_admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    created = False
    try:
        with admin_engine.connect() as connection:
            connection.execute(sa.text(f"CREATE DATABASE {quoted_database_name}"))
        created = True

        test_url = postgres_admin_url.set(database=database_name)
        rendered_test_url = test_url.render_as_string(hide_password=False)
        command.upgrade(_alembic_config(rendered_test_url), "head")
        yield rendered_test_url
    finally:
        if created:
            _validate_generated_database_name(database_name)
            with admin_engine.connect() as connection:
                connection.execute(
                    sa.text(
                        "SELECT pg_terminate_backend(pid) "
                        "FROM pg_stat_activity "
                        "WHERE datname = :database_name "
                        "AND pid <> pg_backend_pid()"
                    ),
                    {"database_name": database_name},
                )
                connection.execute(sa.text(f"DROP DATABASE {quoted_database_name}"))
        admin_engine.dispose()


@pytest.fixture(scope="session")
def postgres_database_url(postgres_admin_url: URL) -> Iterator[str]:
    with _temporary_postgres_database(postgres_admin_url) as database_url:
        yield database_url


@pytest.fixture
def second_postgres_database_url(postgres_admin_url: URL) -> Iterator[str]:
    with _temporary_postgres_database(postgres_admin_url) as database_url:
        yield database_url


@pytest.fixture(scope="session")
def postgres_engine(postgres_database_url: str) -> Iterator[Engine]:
    runtime = create_database_runtime(postgres_database_url)
    try:
        yield runtime.engine
    finally:
        runtime.dispose()


@pytest.fixture
def db_session(postgres_engine: Engine) -> Iterator[Session]:
    session = Session(postgres_engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        inspector = sa.inspect(postgres_engine)
        if DOMAIN_TABLES.issubset(set(inspector.get_table_names())):
            with postgres_engine.begin() as connection:
                connection.execute(
                    sa.text(
                        "TRUNCATE TABLE group_invites, confirmed_session_rsvps, confirmed_sessions, availability, group_memberships, "
                        "groups, users, account_identities, accounts CASCADE"
                    )
                )


@pytest.fixture
def alembic_config(postgres_database_url: str) -> Config:
    return _alembic_config(postgres_database_url)


@pytest.fixture
def run_alembic() -> Callable[[Config, str, str], None]:
    def run(config: Config, operation: str, revision: str) -> None:
        if operation == "upgrade":
            command.upgrade(config, revision)
        elif operation == "downgrade":
            command.downgrade(config, revision)
        else:
            raise ValueError(f"Unsupported Alembic operation: {operation}")

    return run
