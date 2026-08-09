from pathlib import Path

from fastapi.testclient import TestClient


def test_health_returns_only_safe_liveness_state(
    client: TestClient,
    database_path: Path,
) -> None:
    response = client.get("/test-health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    response_text = response.text.lower()
    assert "database_path" not in response_text
    assert "db_file" not in response_text
    assert str(database_path).lower() not in response_text
