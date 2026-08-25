from pathlib import Path

import pytest


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
