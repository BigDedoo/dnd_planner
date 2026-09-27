"""Terms gating uses real authentication/dependencies and synthetic accounts only."""

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from backend.models import Account, User
from backend.terms import CURRENT_TERMS_VERSION
from backend.tests.test_phase_2b_auth import (
    client as client,
)
from backend.tests.test_phase_2b_auth import (
    mock_authenticator as mock_authenticator,
)
from backend.tests.test_phase_2b_auth import (
    phase2b_app as phase2b_app,
)
from backend.tests.test_phase_2b_auth import (
    phase2b_sqlite_runtime as phase2b_sqlite_runtime,
)

pytestmark = pytest.mark.unaccepted_terms


@pytest.fixture
def headers(mock_authenticator):
    mock_authenticator.add_session("terms-test", "terms-subject", display_name="Player")
    return {"Authorization": "Bearer terms-test"}


def test_null_acceptance_rights_access_and_planner_gate(client, headers):
    for path in ("/api/me", "/api/me/terms", "/api/onboarding"):
        result = client.get(path, headers=headers)
        assert result.status_code == 200
        assert result.json()["terms_accepted"] is False
        assert result.json()["terms_version"] is None
        assert result.json()["terms_accepted_at"] is None
    exported = client.get("/api/me/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["account"]["terms_version"] is None
    group_id = uuid.uuid4()
    blocked = [
        client.get("/api/me/groups", headers=headers),
        client.get(f"/api/groups/{group_id}", headers=headers),
        client.post("/api/groups", headers=headers, json={"name": "Blocked"}),
        client.post(
            "/api/onboarding", headers=headers, json={"display_name": "Blocked"}
        ),
        client.get(
            "/api/me/confirmed-sessions?start=2026-09-01&end=2026-10-01",
            headers=headers,
        ),
    ]
    for response in blocked:
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "terms_acceptance_required"
    assert client.get("/api/onboarding", headers=headers).json()["linked"] is False


@pytest.mark.parametrize("version", ["", "old", "2099-01-01", "arbitrary"])
def test_rejects_noncurrent_versions(client, headers, version):
    response = client.put(
        "/api/me/terms", headers=headers, json={"terms_version": version}
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "terms_version_changed"
    assert (
        client.get("/api/me/terms", headers=headers).json()["terms_accepted_at"] is None
    )


def test_acceptance_server_time_idempotence_onboarding_and_export(client, headers):
    assert (
        client.put(
            "/api/me/terms", json={"terms_version": CURRENT_TERMS_VERSION}
        ).status_code
        == 401
    )
    payload = {"terms_version": CURRENT_TERMS_VERSION}
    before = datetime.now(timezone.utc)
    first = client.put("/api/me/terms", headers=headers, json=payload)
    assert first.status_code == 200 and first.json()["terms_accepted"]
    stamp = datetime.fromisoformat(
        first.json()["terms_accepted_at"].replace("Z", "+00:00")
    )
    assert before <= stamp <= datetime.now(timezone.utc)
    second = client.put("/api/me/terms", headers=headers, json=payload)
    # SQLite fixtures may return a naive datetime; the actual PostgreSQL test checks timezone.
    assert second.json()["terms_accepted_at"].removesuffix("Z") == first.json()[
        "terms_accepted_at"
    ].removesuffix("Z")
    created = client.post(
        "/api/onboarding", headers=headers, json={"display_name": "First name"}
    )
    again = client.post(
        "/api/onboarding", headers=headers, json={"display_name": "Do not replace"}
    )
    assert created.status_code == again.status_code == 201
    assert created.json()["user_id"] == again.json()["user_id"]
    assert client.get("/api/me/groups", headers=headers).status_code == 200
    export = client.get("/api/me/export", headers=headers).json()
    assert export["account"]["terms_version"] == CURRENT_TERMS_VERSION
    assert export["account"]["terms_accepted_at"]
    assert export["profile"]["display_name"] == "First name"


@pytest.mark.parametrize("old_version", [None, "2025-01-01"])
def test_existing_linked_accounts_reaccept_without_new_profile(
    client, headers, phase2b_sqlite_runtime, old_version
):
    account_id = uuid.UUID(client.get("/api/me", headers=headers).json()["id"])
    with phase2b_sqlite_runtime.open_session() as session:
        account = session.get(Account, account_id)
        account.terms_version = old_version
        account.terms_accepted_at = (
            datetime(2025, 1, 1, tzinfo=timezone.utc) if old_version else None
        )
        user = User(account_id=account_id, display_name="Existing player")
        session.add(user)
        session.commit()
        user_id = str(user.id)
    status = client.get("/api/onboarding", headers=headers).json()
    assert (
        status["linked"]
        and not status["terms_accepted"]
        and status["user_id"] == user_id
    )
    assert client.get("/api/me/groups", headers=headers).status_code == 403
    assert (
        client.get("/api/me/notification-preferences", headers=headers).status_code
        == 200
    )
    assert client.get("/api/me/export", headers=headers).status_code == 200
    assert (
        client.put(
            "/api/me/terms",
            headers=headers,
            json={"terms_version": CURRENT_TERMS_VERSION},
        ).status_code
        == 200
    )
    assert client.get("/api/me/groups", headers=headers).status_code == 200
    with phase2b_sqlite_runtime.open_session() as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(User)) == 1
        assert str(session.scalar(sa.select(User)).id) == user_id


def test_mutation_guard_and_client_cannot_supply_acceptance_timestamp(
    client, headers, phase2b_app
):
    assert (
        client.put(
            "/api/me/terms",
            headers=headers,
            json={
                "terms_version": CURRENT_TERMS_VERSION,
                "terms_accepted_at": "2000-01-01",
            },
        ).status_code
        == 422
    )
    phase2b_app.state.settings.mutations_enabled = False
    assert (
        client.put(
            "/api/me/terms",
            headers=headers,
            json={"terms_version": CURRENT_TERMS_VERSION},
        ).status_code
        == 503
    )
    assert client.get("/api/me/export", headers=headers).status_code == 200
