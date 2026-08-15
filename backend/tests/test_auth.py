from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import jwt
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.auth import (
    CLERK_PROVIDER,
    DefaultTokenVerifier,
    TokenVerificationError,
    resolve_or_provision_account,
)
from backend.config import Settings
from backend.db import DatabaseRuntime
from backend.main import create_app
from backend.models import (
    Account,
    AccountIdentity,
    Base,
    Group,
    GroupMembership,
    MembershipRole,
    User,
)


class MockTokenVerifier:
    def __init__(self) -> None:
        self.valid_tokens: dict[str, dict[str, Any]] = {}

    def add_token(
        self,
        token: str,
        sub: str,
        email: str | None = None,
        display_name: str | None = None,
        azp: str | None = None,
    ) -> None:
        self.valid_tokens[token] = {
            "sub": sub,
            "email": email,
            "display_name": display_name,
            "azp": azp,
        }

    def verify(self, token: str, settings: Settings) -> dict[str, Any]:
        if token not in self.valid_tokens:
            raise TokenVerificationError("Invalid test token")
        payload = self.valid_tokens[token]
        azp = payload.get("azp")
        if azp and settings.clerk_authorized_parties:
            if azp not in settings.clerk_authorized_parties:
                raise TokenVerificationError(f"Unauthorized party: {azp}")
        return payload


@pytest.fixture
def mock_verifier() -> MockTokenVerifier:
    return MockTokenVerifier()


@pytest.fixture
def auth_sqlite_runtime(tmp_path: Path) -> Iterator[DatabaseRuntime]:
    db_file = tmp_path / "auth_test.db"
    engine = create_engine(f"sqlite:///{db_file}")

    @sa.event.listens_for(engine, "connect")
    def _register_sqlite_functions(dbapi_connection, _):
        dbapi_connection.create_function(
            "btrim", 1, lambda s: s.strip() if s is not None else None
        )

    Base.metadata.create_all(engine)
    runtime = DatabaseRuntime(engine=engine, safe_url=f"sqlite:///{db_file}")
    yield runtime
    runtime.dispose()


@pytest.fixture
def auth_app(
    auth_sqlite_runtime: DatabaseRuntime,
    mock_verifier: MockTokenVerifier,
) -> FastAPI:
    test_settings = Settings(
        _env_file=None,
        APP_ENV="test",
        LOG_LEVEL="CRITICAL",
        CORS_ALLOWED_ORIGINS=["http://testserver"],
    )
    application = create_app(test_settings, database_runtime=auth_sqlite_runtime)

    with (
        patch("backend.main.validate_database_readiness"),
        patch("backend.main.compatibility.validate_compatibility_dataset"),
    ):
        application.state.token_verifier = mock_verifier
        yield application


@pytest.fixture
def client(auth_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(auth_app) as test_client:
        yield test_client


def test_unauthenticated_me_returns_401(client: TestClient) -> None:
    response = client.get("/api/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization header"


def test_invalid_auth_header_format_returns_401(client: TestClient) -> None:
    response = client.get("/api/me", headers={"Authorization": "InvalidToken"})
    assert response.status_code == 401
    assert "Expected 'Bearer <token>'" in response.json()["detail"]


def test_invalid_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/me", headers={"Authorization": "Bearer bad-token"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Could not validate credentials"


def test_valid_token_provisions_internal_account(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    token = "valid-token-user-1"
    sub = "user_clerk_12345"
    mock_verifier.add_token(
        token=token,
        sub=sub,
        email="test@example.com",
        display_name="Test Adventurer",
    )

    response = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    account_id = data["id"]
    assert account_id is not None
    assert uuid.UUID(account_id)
    assert data["email"] == "test@example.com"
    assert data["display_name"] == "Test Adventurer"

    # Verify internal primary key is NOT the Clerk user ID
    assert account_id != sub

    # Verify in database
    session = auth_sqlite_runtime.open_session()
    account = session.get(Account, uuid.UUID(account_id))
    assert account is not None
    assert account.email == "test@example.com"
    assert len(account.identities) == 1
    assert account.identities[0].provider == CLERK_PROVIDER
    assert account.identities[0].provider_subject == sub
    session.close()


def test_repeated_requests_return_same_account_id(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
) -> None:
    token = "valid-token-repeated"
    sub = "user_clerk_repeated"
    mock_verifier.add_token(token=token, sub=sub, email="repeat@example.com")

    resp1 = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    resp2 = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["id"] == resp2.json()["id"]


def test_different_provider_subjects_produce_different_accounts(
    client: TestClient,
    mock_verifier: MockTokenVerifier,
) -> None:
    token_a = "token-user-a"
    token_b = "token-user-b"
    mock_verifier.add_token(token=token_a, sub="user_a", email="a@example.com")
    mock_verifier.add_token(token=token_b, sub="user_b", email="b@example.com")

    resp_a = client.get("/api/me", headers={"Authorization": f"Bearer {token_a}"})
    resp_b = client.get("/api/me", headers={"Authorization": f"Bearer {token_b}"})

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["id"] != resp_b.json()["id"]
    assert resp_a.json()["email"] == "a@example.com"
    assert resp_b.json()["email"] == "b@example.com"


def test_default_token_verifier_claim_validation() -> None:
    verifier = DefaultTokenVerifier()
    app_settings = Settings(
        _env_file=None,
        CLERK_AUTHORIZED_PARTIES=["http://localhost:3000"],
    )

    # Valid token
    valid_payload = {"sub": "user_123", "azp": "http://localhost:3000"}
    token = jwt.encode(
        valid_payload, "test-secret-at-least-32-bytes-long", algorithm="HS256"
    )
    result = verifier.verify(token, app_settings)
    assert result["sub"] == "user_123"

    # Missing sub
    token_no_sub = jwt.encode(
        {"email": "test@example.com"},
        "test-secret-at-least-32-bytes-long",
        algorithm="HS256",
    )
    with pytest.raises(TokenVerificationError, match="missing a valid 'sub' claim"):
        verifier.verify(token_no_sub, app_settings)

    # Unauthorized azp
    token_bad_azp = jwt.encode(
        {"sub": "user_123", "azp": "http://evil.com"},
        "test-secret-at-least-32-bytes-long",
        algorithm="HS256",
    )
    with pytest.raises(TokenVerificationError, match="authorized parties"):
        verifier.verify(token_bad_azp, app_settings)


def test_legacy_users_and_groups_are_isolated_from_accounts(
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = auth_sqlite_runtime.open_session()

    # Create a legacy user and group
    legacy_user_id = uuid.uuid4()
    legacy_user = User(
        id=legacy_user_id,
        display_name="Legacy Aragon",
        timezone="UTC",
    )
    group = Group(
        id=uuid.uuid4(),
        name="Fellowship",
        timezone="UTC",
    )
    membership = GroupMembership(
        group_id=group.id,
        user_id=legacy_user.id,
        role=MembershipRole.OWNER,
        display_order=0,
    )
    session.add_all([legacy_user, group, membership])
    session.commit()

    # Provision a Clerk account
    clerk_account = resolve_or_provision_account(
        session=session,
        provider="clerk",
        provider_subject="user_fellowship_clerk",
        email="clerk@fellowship.org",
        display_name="Clerk Aragon",
    )

    # Ensure internal account ID is completely separate from legacy user ID
    assert clerk_account.id != legacy_user_id
    assert session.query(User).count() == 1
    assert session.query(Account).count() == 1
    assert session.query(AccountIdentity).count() == 1

    # Verify legacy user properties unchanged
    refetched_legacy_user = session.get(User, legacy_user_id)
    assert refetched_legacy_user is not None
    assert refetched_legacy_user.display_name == "Legacy Aragon"
    assert len(refetched_legacy_user.memberships) == 1

    session.close()


def test_idempotent_account_provisioning(
    auth_sqlite_runtime: DatabaseRuntime,
) -> None:
    session = auth_sqlite_runtime.open_session()

    account1 = resolve_or_provision_account(
        session=session,
        provider="clerk",
        provider_subject="user_unique_1",
        email="unique@example.com",
    )
    account2 = resolve_or_provision_account(
        session=session,
        provider="clerk",
        provider_subject="user_unique_1",
        email="unique@example.com",
    )

    assert account1.id == account2.id
    assert session.query(Account).count() == 1
    assert session.query(AccountIdentity).count() == 1
    session.close()
