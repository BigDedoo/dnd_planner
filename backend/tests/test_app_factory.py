from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import DatabaseConfigurationError, create_database_runtime
from backend.main import create_app


def test_mutations_enabled_is_typed_and_explicit(tmp_path: Path) -> None:
    disabled = Settings(
        _env_file=None,
        DATABASE_PATH=tmp_path / "unused-legacy.db",
        MUTATIONS_ENABLED="false",
    )
    enabled = Settings(
        _env_file=None,
        DATABASE_PATH=tmp_path / "unused-legacy.db",
        MUTATIONS_ENABLED="true",
    )

    assert disabled.mutations_enabled is False
    assert enabled.mutations_enabled is True


def test_normal_runtime_requires_database_url_without_injected_runtime(
    tmp_path: Path,
) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            DATABASE_PATH=tmp_path / "unused-legacy.db",
            DATABASE_URL=None,
        )
    )

    with pytest.raises(DatabaseConfigurationError, match="DATABASE_URL is required"):
        with TestClient(application):
            pass


def test_normal_runtime_rejects_non_psycopg_database_driver(
    tmp_path: Path,
) -> None:
    application = create_app(
        Settings(
            _env_file=None,
            DATABASE_PATH=tmp_path / "unused-legacy.db",
            DATABASE_URL="sqlite:///not-a-runtime-target.db",
        )
    )

    with pytest.raises(DatabaseConfigurationError, match=r"postgresql\+psycopg"):
        with TestClient(application):
            pass


def test_injected_runtime_must_match_explicit_database_url(
    tmp_path: Path,
) -> None:
    configured_url = "postgresql+psycopg://user:secret@127.0.0.1/configured"
    injected_url = "postgresql+psycopg://user:secret@127.0.0.1/injected"
    runtime = create_database_runtime(injected_url)
    application = create_app(
        Settings(
            _env_file=None,
            DATABASE_PATH=tmp_path / "unused-legacy.db",
            DATABASE_URL=configured_url,
        ),
        runtime,
    )

    with pytest.raises(DatabaseConfigurationError, match="does not match"):
        with TestClient(application):
            pass
