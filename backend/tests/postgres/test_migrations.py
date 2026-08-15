from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
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
from backend.models import User

DOMAIN_TABLES = {"users", "groups", "group_memberships", "availability"}
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
    assert head_revision == "0002_phase_2a_accounts"
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

    assert _current_revision(postgres_engine) == "0002_phase_2a_accounts"
