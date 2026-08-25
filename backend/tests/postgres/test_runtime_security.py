from __future__ import annotations

import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.db import DatabaseReadinessError, DatabaseRuntime, create_database_runtime
from backend.main import create_app
from backend.models import Group, GroupMembership, MembershipRole, User


def _build_application(
    database_url: str,
    tmp_path: Path,
) -> tuple[FastAPI, DatabaseRuntime]:
    runtime = create_database_runtime(database_url)
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="CRITICAL",
            DATABASE_PATH=tmp_path / "unused-synthetic.db",
            DATABASE_URL=database_url,
            CORS_ALLOWED_ORIGINS=["http://testserver"],
        ),
        runtime,
    )
    return application, runtime


def test_startup_requires_only_database_readiness_not_historical_groups(
    tmp_path: Path,
    postgres_database_url: str,
    db_session: Session,
) -> None:
    users = [
        User(id=uuid.uuid4(), display_name="First owner", timezone="UTC"),
        User(id=uuid.uuid4(), display_name="Second owner", timezone="UTC"),
    ]
    groups = [
        Group(id=uuid.uuid4(), name="Green flag", timezone="UTC"),
        Group(id=uuid.uuid4(), name="Green flag", timezone="Europe/Paris"),
    ]
    db_session.add_all([*users, *groups])
    db_session.flush()
    db_session.add_all(
        [
            GroupMembership(
                group_id=groups[index].id,
                user_id=users[index].id,
                role=MembershipRole.OWNER,
                display_order=0,
            )
            for index in range(2)
        ]
    )
    db_session.commit()

    application, runtime = _build_application(postgres_database_url, tmp_path)
    with TestClient(application) as client:
        assert client.get("/test-health").json() == {"status": "ok"}
        assert application.state.database_runtime is runtime


def test_legacy_public_methods_are_not_registered_or_accessible(
    tmp_path: Path,
    postgres_database_url: str,
) -> None:
    application, _ = _build_application(postgres_database_url, tmp_path)
    paths = application.openapi()["paths"]

    assert "get" not in paths["/groups"]
    assert "get" not in paths["/api/groups"]
    assert "/availability/{group}/{year}/{month}" not in paths
    assert "/availability" not in paths
    assert "/admin/all-availability" not in paths

    with TestClient(application) as client:
        requests = [
            client.get("/groups"),
            client.get("/availability/Green%20flag/2026/8"),
            client.post(
                "/availability",
                json={
                    "group": "Green flag",
                    "user": "Synthetic player",
                    "date": "2026-08-25",
                    "status": "Available",
                },
            ),
            client.get("/admin/all-availability?start=2026-08-01&end=2026-08-31"),
        ]
        assert all(response.status_code in {404, 405} for response in requests)
        assert client.get("/api/me/groups").status_code == 401


def test_explicit_injected_runtime_does_not_require_database_url_setting(
    tmp_path: Path,
    postgres_database_url: str,
) -> None:
    runtime = create_database_runtime(postgres_database_url)
    application = create_app(
        Settings(
            _env_file=None,
            APP_ENV="test",
            LOG_LEVEL="CRITICAL",
            DATABASE_PATH=tmp_path / "unused-synthetic.db",
            DATABASE_URL=None,
            CORS_ALLOWED_ORIGINS=["http://testserver"],
        ),
        runtime,
    )

    with TestClient(application) as client:
        assert client.get("/test-health").json() == {"status": "ok"}


def test_startup_rejects_wrong_revision_without_leaking_password(
    tmp_path: Path,
    postgres_database_url: str,
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            sa.text("UPDATE alembic_version SET version_num = 'unexpected_revision'")
        )
    application, _ = _build_application(postgres_database_url, tmp_path)
    password = sa.engine.make_url(postgres_database_url).password

    try:
        with pytest.raises(DatabaseReadinessError, match="expected") as error:
            with TestClient(application):
                pass
        assert password is not None
        assert password not in str(error.value)
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                sa.text(
                    "UPDATE alembic_version "
                    "SET version_num = '0009_session_notifications'"
                )
            )
