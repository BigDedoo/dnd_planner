from pathlib import Path

from fastapi.testclient import TestClient

from backend.config import Settings, settings
from backend.main import create_app


def test_app_instances_keep_settings_and_databases_isolated(tmp_path: Path) -> None:
    first_path = tmp_path / "first.db"
    second_path = tmp_path / "second.db"
    global_database_path = settings.database_path

    first_app = create_app(Settings(_env_file=None, DATABASE_PATH=first_path))
    second_app = create_app(Settings(_env_file=None, DATABASE_PATH=second_path))

    with (
        TestClient(first_app) as first_client,
        TestClient(second_app) as second_client,
    ):
        response = first_client.post(
            "/availability",
            json={
                "group": "Green flag",
                "user": "Quentin",
                "date": "2026-01-01",
                "status": "Available",
            },
        )

        assert response.status_code == 200
        assert len(first_client.get("/availability/Green flag/2026/1").json()) == 1
        assert second_client.get("/availability/Green flag/2026/1").json() == []
        assert first_app.state.settings.database_path == first_path
        assert second_app.state.settings.database_path == second_path
        assert settings.database_path == global_database_path

    assert first_path.is_file()
    assert second_path.is_file()
