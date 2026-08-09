from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.main import create_app


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
def isolated_database_environment(
    monkeypatch: pytest.MonkeyPatch,
    database_path: Path,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "CRITICAL")
    monkeypatch.setenv("DATABASE_PATH", str(database_path))
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["http://testserver"]')


@pytest.fixture
def app(database_path: Path, isolated_database_environment: None) -> FastAPI:
    test_settings = Settings(_env_file=None)
    assert test_settings.database_path == database_path
    return create_app(test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
