from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.config import Settings
from backend.db import (
    DatabaseReadinessError,
    DatabaseRuntime,
    check_database_connection,
)
from backend.main import create_app


def _build_application(tmp_path: Path) -> tuple[FastAPI, DatabaseRuntime]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    runtime = DatabaseRuntime(engine=engine, safe_url="sqlite:///:memory:")
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
    return application, runtime


def test_liveness_does_not_query_database(tmp_path: Path) -> None:
    application, _ = _build_application(tmp_path)

    with (
        patch("backend.main.validate_database_readiness"),
        patch("backend.main.check_database_connection") as database_check,
        TestClient(application) as client,
    ):
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/live").json() == {"status": "alive"}
        database_check.assert_not_called()


def test_readiness_queries_current_database_runtime(tmp_path: Path) -> None:
    application, runtime = _build_application(tmp_path)

    with (
        patch("backend.main.validate_database_readiness"),
        patch("backend.main.check_database_connection") as database_check,
        TestClient(application) as client,
    ):
        first_response = client.get("/health/ready")
        second_response = client.get("/health/ready")

    assert first_response.status_code == 200
    assert first_response.json() == {"status": "ready"}
    assert second_response.status_code == 200
    assert second_response.json() == {"status": "ready"}
    assert database_check.call_count == 2
    database_check.assert_called_with(runtime)


def test_readiness_failure_returns_sanitized_503(tmp_path: Path) -> None:
    application, _ = _build_application(tmp_path)
    sensitive_diagnostic = (
        "postgresql+psycopg://db_user:db_password@database.internal/dnd_planner"
    )

    with (
        patch("backend.main.validate_database_readiness"),
        patch(
            "backend.main.check_database_connection",
            side_effect=DatabaseReadinessError(sensitive_diagnostic),
        ),
        TestClient(application) as client,
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "db_user" not in response.text
    assert "db_password" not in response.text
    assert sensitive_diagnostic not in response.text


def test_legacy_health_endpoint_remains_compatible(tmp_path: Path) -> None:
    application, _ = _build_application(tmp_path)

    with (
        patch("backend.main.validate_database_readiness"),
        TestClient(application) as client,
    ):
        response = client.get("/test-health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_check_uses_select_one_and_releases_connection() -> None:
    runtime = MagicMock(spec=DatabaseRuntime)
    connection_context = runtime.engine.connect.return_value
    connection = connection_context.__enter__.return_value

    check_database_connection(runtime)

    connection.execute.assert_called_once()
    statement = connection.execute.call_args.args[0]
    assert str(statement) == "SELECT 1"
    connection_context.__exit__.assert_called_once()
