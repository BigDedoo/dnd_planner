from collections.abc import Callable, Iterator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend import database
from backend.config import Settings


class LegacyAvailabilityUpdate(BaseModel):
    group: str
    user: str
    date: date
    status: str | None


def _create_legacy_test_app(test_settings: Settings) -> FastAPI:
    """Build the explicit SQLite rollback oracle; never used by normal runtime."""

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.init_db(test_settings.database_path)
        yield

    application = FastAPI(lifespan=lifespan)

    @application.get("/groups")
    def groups():
        return [
            {"name": name, "players": players}
            for name, players in database.GROUPS.items()
        ]

    @application.get("/availability/{group}/{year}/{month}")
    def month(group: str, year: int, month: int):
        return database.get_group_month_availability(
            group,
            year,
            month,
            test_settings.database_path,
        )

    @application.post("/availability")
    def write(update: LegacyAvailabilityUpdate):
        database.set_user_availability(
            update.group,
            update.user,
            update.date,
            update.status,
            test_settings.database_path,
        )
        return {"status": "success", "new_state": update.status}

    @application.get("/admin/all-availability")
    def admin(start: date, end: date):
        return database.get_all_availability(
            start.isoformat(),
            end.isoformat(),
            test_settings.database_path,
        )

    @application.get("/test-health")
    def health():
        return {"status": "ok"}

    return application


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
def legacy_app_factory() -> Callable[[Settings], FastAPI]:
    return _create_legacy_test_app


@pytest.fixture
def legacy_app(
    database_path: Path,
    isolated_database_environment: None,
    legacy_app_factory: Callable[[Settings], FastAPI],
) -> FastAPI:
    test_settings = Settings(_env_file=None)
    assert test_settings.database_path == database_path
    return legacy_app_factory(test_settings)


@pytest.fixture
def legacy_client(legacy_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(legacy_app) as test_client:
        yield test_client
